#!/usr/bin/env python3
import re
import logging
from pathlib import Path
from glob import glob
import socket
import sys
import shutil
import time

import click
from copy import deepcopy
from click_loglevel import LogLevel

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from selenium.webdriver import ActionChains

import yaml

log = logging.getLogger(__name__)

# yaml issue https://github.com/yaml/pyyaml/issues/240
def str_presenter(dumper, data):
    """configures yaml for dumping multiline strings
    Ref: https://stackoverflow.com/questions/8640959/how-can-i-control-what-scalar-form-pyyaml-uses-for-my-data"""
    # if "Really attended UC Riverside" in str(data):
    #     import pdb; pdb.set_trace()
    if data.count('\n') > 0:  # check for multiline string
        # remove trailing whitespaces which we do not care about since they could force use of str form
        # https://github.com/yaml/pyyaml/issues/121
        fixed_data = "\n".join(line.rstrip() for line in data.splitlines())
        return dumper.represent_scalar('tag:yaml.org,2002:str', fixed_data, style='|')
    return dumper.represent_scalar('tag:yaml.org,2002:str', data)

yaml.add_representer(str, str_presenter)
yaml.representer.SafeRepresenter.add_representer(str, str_presenter) # to use with safe_dum


class Webshotter:
    def __init__(self, login, password, headless):
        self.login_url = "https://searchjobs.dartmouth.edu/hr/sessions/new"
        self.login = login
        self.password = password
        self.set_driver(headless)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.driver.quit()

    def set_driver(self, headless):
        options = Options()
        options.add_argument("--no-sandbox")
        if headless:
            options.add_argument("--headless")
        options.add_argument("--incognito")
        # options.add_argument('--disable-gpu')
        options.add_argument("--window-size=1024,1400")
        options.add_argument("--disable-dev-shm-usage")
        # driver.set_page_load_timeout(30)
        # driver.set_script_timeout(30)
        # driver.implicitly_wait(10)
        self.driver = webdriver.Chrome(options=options)
        self.do_login()
        # warm up
        # self.driver.get(self.login_url)

    def do_login(self):
        self.driver.get(self.login_url)
        username_field = self.driver.find_element(value="user_username")
        password_field = self.driver.find_element(value="user_password")
        username_field.send_keys(self.login)
        password_field.send_keys(self.password)
        self.driver.find_elements(by=By.TAG_NAME, value="form")[0].submit()

    def reset_driver(self):
        try:
            self.driver.quit()  # cleanup if still can
        finally:
            self.set_driver()

    def wait_no_progressbar(self, cls):
        WebDriverWait(self.driver, 300, poll_frequency=0.1).until(
            EC.invisibility_of_element_located((By.CLASS_NAME, cls))
        )


    # method to get the downloaded file name
    # from https://stackoverflow.com/a/56570364/1265472
    def getDownLoadedFileName(self, waitTime):
        driver = self.driver
        driver.execute_script("window.open()")
        # switch to new tab
        driver.switch_to.window(driver.window_handles[-1])
        # navigate to chrome downloads
        driver.get('chrome://downloads')
        # define the endTime
        endTime = time.time()+waitTime
        while True:
            try:
                import pdb; pdb.set_trace()
                # get downloaded percentage
                downloadPercentage = driver.execute_script(
                    "return document.querySelector('downloads-manager').shadowRoot.querySelector('#downloadsList downloads-item').shadowRoot.querySelector('#progress').value")
                # check if downloadPercentage is 100 (otherwise the script will keep waiting)
                if downloadPercentage == 100:
                    # return the file name once the download is completed
                    return driver.execute_script("return document.querySelector('downloads-manager').shadowRoot.querySelector('#downloadsList downloads-item').shadowRoot.querySelector('div#content  #file-link').text")
            except:
                pass
            time.sleep(1)
            if time.time() > endTime:
                break

    def get_candidates(self):
        applicants_link = self.driver.find_elements(By.PARTIAL_LINK_TEXT, "Applicants")[0]
        applicants_link.click()

        table = self.driver.find_elements(By.XPATH, '//*[@id="results"]')[0]
        candidates = {}

        rows = table.find_elements(By.XPATH, './/tr')[1:]  # skip header
        for row in rows:
            cand_id = row.get_attribute('data-id')
            cells = [_.text for _ in row.find_elements(By.XPATH, './/td')]
            for a in row.find_elements(By.XPATH, './/a'):
                href = a.get_attribute('href')
                res = re.match('https://searchjobs\.dartmouth\.edu/hr/job_applications/([0-9]+)', href)
                if not res:
                    continue
            assert res.groups()[0] == cand_id
            cand_id = int(cand_id)
            candidates[cand_id] = {
                "id": cand_id,
                "url": href,
                "last_name": cells[1],
                "first_name": cells[2],
                "application_date": cells[4],
                "application_state": cells[5],
            }
        return candidates

    def process_candidate(self, cand_rec, outpath, try_download=True):
        self.driver.get(cand_rec["url"])
        candidate = {}
        content_table = self.driver.find_elements(by=By.CLASS_NAME, value='list-table')
        #for d, field in dict(first=2, last=4, state=9, need_visa=17):
        def find_table_by_caption(target_caption):
            for table in self.driver.find_elements(By.XPATH, '//table'):
                captions = t.find_elements(By.XPATH, './/caption')
                if captions and captions[0].text == target_caption:
                    # we have the table!
                    return table
        # might not work...
        # contact_info_table = find_table_by_caption("Contact Information")
        tables = self.driver.find_elements(By.XPATH, '//table')
        contact_info_fields = list(
            zip(
                *([_.text for _ in tables[1].find_elements(By.XPATH, './/' + x)]
                  for x in ['th', 'td'])
                )
        )
        # tune up
        #contact_info = dict(
        #    (v1.lower().replace(' ', '_'), v2) for v1, v2 in contact_info_fields if v2
        #)
        contact_info = dict(contact_info_fields)
        assert cand_rec['first_name'] == contact_info['First Name']
        assert cand_rec['last_name'] == contact_info['Last Name']
        #cand_rec.update(contact_info)
        cand_rec['email'] = contact_info['Please indicate your email address']
        cand_rec['need_visa'] = contact_info['Will you now or in the future require sponsorship for employment visa status (e.g., H-1B visa status)?']
        cand_rec['phone'] = contact_info['Primary Contact Number']
        cand_rec['address'] = ', '.join(contact_info[_] for _ in ['Address1', 'City', 'State', 'Country'] if contact_info[_])
        cand_rec['schedule'] = contact_info['Work schedule desired?']


        # Populate more metadata
        # Generate/save combined doc
        generate_combo = self.driver.find_elements(by=By.CLASS_NAME, value='generate-one-combo')
        combined_container = self.driver.find_elements(by=By.CLASS_NAME, value='combined-doc-container')
        if generate_combo:
            assert len(generate_combo) == 1
            if not combined_container or combined_container[0].text == 'Generate':
                generate_combo[0].click()

        _ = WebDriverWait(
            self.driver, 300, poll_frequency=0.1).until(
                EC.visibility_of_element_located((By.LINK_TEXT, 'Regenerate')))
        combined_container = self.driver.find_elements(by=By.CLASS_NAME, value='combined-doc-container')[0]
        if not combined_container and not _:
            raise RuntimeError("Could not find combined document or Regenerate")
        #assert len(combined_container) == 1
        outpath = Path(outpath)
        outpath.mkdir(parents=True, exist_ok=True)
        outpath /= "combined.pdf"
        if not outpath.exists() and try_download:
            import pyautogui
            pdf_a = combined_container.find_element(By.LINK_TEXT, "View")
            actionChain = ActionChains(self.driver)
            actionChain.context_click(pdf_a).perform()
            time.sleep(1)
            log.info("Download the file and move into %s", outpath)
            pyautogui.typewrite(['down']*3 + ['enter'], interval=0.2)
            # could not figure out how to automate fully!
            # out_filename = self.getDownLoadedFileName(120)
            #input("enter anything whenever done")
            glob_pdf = '/home/yoh/Downloads/[0-9][0-9][0-9][0-9][0-9][0-9].pdf'
            assert not glob(glob_pdf)
            for i in range(40):
                time.sleep(1)
                pdfs = glob(glob_pdf)
                if pdfs:
                    assert len(pdfs) == 1
                    shutil.move(pdfs[0], outpath)
                    break

        # used to have this field
        cand_rec.pop('has_combined', None)
        if outpath.is_symlink() or outpath.exists():
            # suboptimal: hardcoded hierarchy assumption
            cand_rec['combined'] = str(outpath.relative_to(outpath.parent.parent))
        else:
            cand_rec['combined'] = ''
            log.warning("%s absent", outpath)


def process_position(login, password, out_dir, headless=False, just_load_save=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates_yaml = out_dir / "candidates.yaml"
    if candidates_yaml.exists():
        candidates = yaml.load(candidates_yaml.open(), Loader=yaml.SafeLoader) or {}
    else:
        candidates = {}
    if just_load_save:
        with candidates_yaml.open('w') as f:
            yaml.dump(candidates, f)
        return candidates
    orig_candidates = deepcopy(candidates)
    try:
        log.info("Login-ing")
        with Webshotter(login, password, headless=headless) as ws:
            new_candidates = []
            web_candidates = ws.get_candidates()
            log.info("Looking at %d candidates", len(web_candidates))
            for cand_id, cand_rec in web_candidates.items():
                if cand_id not in candidates:
                    cand_rec.update(
                        {
                        'emailed': False,
                        'email': None,  # to come from the page
                        'need_visa': None,
                        'notes': '',  # fields to place notes into etc
                        'folder': f'{cand_id}-{cand_rec["first_name"].lower()}_{cand_rec["last_name"].lower()}',
                        }
                    )
                    new_candidates.append(cand_id)
                else:
                    # may be status got updated
                    candidates[cand_id]['application_state'] = cand_rec['application_state']
                    # and otherwise -- take the one we have
                    cand_rec = candidates[cand_id]
                candidates[cand_id] = cand_rec
                # the ones I decided to add "later" in the game
                cand_rec.setdefault('_verdict_', '')
                cand_rec.setdefault('github', '')
                cand_folder = Path(out_dir) / cand_rec['folder']
                # presence of folder would mean that we processed that candidate

                # empty folder -- useless folder
                try:
                    cand_folder.rmdir()
                except IOError:
                    pass  # must be not empty -- good
                if not cand_folder.exists() or cand_rec['need_visa'] is None:
                    log.info("Candidate %s is being processed", cand_rec['folder'])
                    # now navigate through candidate page and possibly produce his/her combined doc
                    ws.process_candidate(cand_rec, cand_folder, try_download=not headless)
                else:
                    log.info("Candidate %s was already processed", cand_rec['folder'])

        if orig_candidates == candidates:
            log.info("%s: no updates", candidates_yaml)
        else:
            # save all candidates
            (log.info if not new_candidates else log.warning)(
                "%s: updated with %d new", candidates_yaml, len(new_candidates))
            with candidates_yaml.open('w') as f:
                yaml.dump(candidates, f)
        return candidates

    except TimeoutException:
        # This can happen if a timeout occurs inside the Webshotter constructor
        # (e.g., when trying to log in)
        log.debug("Startup timed out")
        t = "timeout"
    except WebDriverException as exc:
        log.warning("Caught %s", str(exc))
        t = str(exc).rstrip()


def setup_exceptionhook(ipython=False):
    """Overloads default sys.excepthook with our exceptionhook handler.

       If interactive, our exceptionhook handler will invoke
       pdb.post_mortem; if not interactive, then invokes default handler.
    """

    def _pdb_excepthook(type, value, tb):
        import traceback

        traceback.print_exception(type, value, tb)
        print()
        import pdb

        pdb.post_mortem(tb)

    if ipython:
        from IPython.core import ultratb
        sys.excepthook = ultratb.FormattedTB(
            mode="Verbose",
            # color_scheme='Linux',
            call_pdb=is_interactive(),
        )
    else:
        sys.excepthook = _pdb_excepthook


@click.command()
@click.option(
    "-o",
    "--output-path",
    type=click.Path(), # exists=True, dir_okay=True, file_okay=False),
    help="top directory where to store data per each position",
    default="positions"
)
@click.option(
    "-i",
    "--positions-file",
    help="File containing positions secrets etc",
    type=click.Path(exists=True, dir_okay=False),
)
@click.option(
    "-l",
    "--log-level",
    type=LogLevel(),
    default=logging.INFO,
    help="Set logging level  [default: INFO]",
)
@click.option(
    "--headless",
    default=False,
    is_flag=True,
    help="Work headless -- then will not try to download since we need to click"
)
@click.option("--pdb", help="Fall into pdb if errors out", is_flag=True)
@click.option("--action", help="Do that action only instead full sweept etc",
              type=click.Choice(['load-save-candidates'], case_sensitive=False),)
@click.argument("positions", nargs=-1, type=list)
def main(output_path, positions, positions_file, log_level, headless, pdb=False, action=None):
    logging.basicConfig(
        format="%(asctime)s [%(levelname)-8s] %(process)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        level=log_level,
    )
    # To guarantee that we time out if something gets stuck:
    socket.setdefaulttimeout(300)

    if pdb:
        setup_exceptionhook()

    import yaml
    with open(positions_file) as f:
        position_recs = yaml.load(f, Loader=yaml.SafeLoader)
    if not positions:
        positions = list(position_recs)

    output_path = Path(output_path)
    output_path.mkdir(exist_ok=True)

    for p in positions:
        out_dir = ( output_path / p)
        position = position_recs[p]

        candidates = process_position(
            position['login'],
            position['password'],
            out_dir,
            headless=headless,
            just_load_save=action == 'load-save-candidates'
        )


if __name__ == "__main__":
    main()
