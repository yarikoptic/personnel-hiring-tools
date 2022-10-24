# Get/update applicants to an open position

A crude selenium script to fetch information about new applicants.  I run it in
headless mode (cannot download pdfs then) via cron-job to fetch metadata
and then if any new candidate run locally to fetch combined PDFs locally.  I
rely on git-annex/datalad to keep copies on those PDFs and configuration file
itself not under git but in annex.

Probably the best setup, is to include this pure git repo as a submodule
(subdataset in DataLad terms) within your dataset with positions which would contain
actual configuration.yaml you provide to the script. That would also follow
YODA principles we promote: see https://github.com/myyoda/myyoda.
