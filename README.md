# Kishi's Job Finder

Care, NHS, pharmacy, lab, admin and school-support jobs in Hull and East Yorkshire, picked for Kishi's experience.

- **Live site:** https://diniverse.github.io/kishis-job-finder/
- **How it updates:** a GitHub Actions job (`.github/workflows/update-jobs.yml`, running `scripts/update_jobs.py`) runs on GitHub's own servers twice a day (07:20 and 16:20 UTC). It searches GOV.UK Find a Job, Teaching Vacancies and Job Clerk for Hull and East Riding care, NHS support, pharmacy, admin and school-support jobs, drops closed jobs and commits a fresh `jobs.json`. GitHub Pages republishes automatically, so refreshing the page shows the latest list. It needs nothing else running; to run it straight away, open the **Actions** tab, choose **Update jobs** and press **Run workflow**. A scheduled Claude task may also add hand-picked jobs to the same file.
- **Saved / Applied / Hidden** marks are stored in each visitor's own browser (nothing personal is stored in this repository).
- CV tailoring, supporting-statement drafts and the shared application tracker live in a private Claude workspace, not here.

Always open the original advert to check details and closing dates before applying.
