# User acceptance test: ArchLens

## Who to test with

Three to five people who have never seen ArchLens. Mix them:

- one or two students or junior developers (like recruiters' typical reviewers of GitHub profiles),
- one person who is not a developer but can read a project page,
- if possible, one person who maintains an open-source or personal project.

Do not coach them. Do not explain the app first. Sit beside them or share their screen, and note where they pause or ask a question.

## Setup

- Use the live demo: https://archlens-xhxr.onrender.com. Open it yourself once, 2 minutes before each test, so the free server is awake. Note in the results if you did not.
- Or run locally from the README: clone the repo, create a virtual environment, `pip install -r requirements.txt`, `alembic upgrade head`, `uvicorn main:app --reload`, open http://127.0.0.1:8000. Set `GITHUB_TOKEN` if you test many times, because GitHub allows only 60 requests per hour without one.
- Use one desktop browser and one phone. Give each tester one repository of their own choice, or a well-known public one if they have none.
- Each person can start 5 new analyses in 10 minutes. Five tasks fit, but do not repeat the test with the same tester in a short time.
- Start a timer for each task. Stop it when the tester says they are done or after 5 minutes.

## Tasks

Read each goal aloud. Do not say where to click.

**T1. Find out what the tool does.**
Goal: "Tell me, in your own words, what this website is for and who it is for."
Pass: the tester says it checks the health or quality of a GitHub repository, and gives a score or fix list, within 30 seconds of the page loading.

**T2. Check a repository.**
Goal: "Get a health result for a repository you know, or for psf/requests."
Pass: the tester reaches a report page with a score without help, in under 2 minutes (excluding any server wake-up time, which you record in notes).

**T3. Understand the result.**
Goal: "Tell me what the score means and what you would fix first."
Pass: the tester names one concrete fix from the report and says roughly what the score means (for example "77 out of 100, good but not perfect").

**T4. Check why the score is what it is.**
Goal: "Find out why one part of the score is low, and where the number comes from."
Pass: the tester finds the evidence for a single dimension or the scoring explanation page, and can say what the tool looked for.

**T5. Keep or share the result, or compare.**
Goal: "Send this result to a friend, or compare it with another repository."
Pass: the tester shares a link, exports the report, copies a badge, or opens a comparison of two repositories. Any one of these counts.

Bonus observation (not a task): ask the tester to type a wrong value such as `hello world` once. Note whether the error message helps them fix it.

## After the test: three questions

1. What was the most confusing or frustrating moment?
2. Would you use this on your own project, or look at someone else's project with it? Why or why not?
3. What is one thing you expected to see that was not there?

## Results

| Tester | T1 | T2 | T3 | T4 | T5 | Time per task (T1/T2/T3/T4/T5) | Notes (waits, confusion, errors, device) |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
| | | | | | | | |
| | | | | | | | |
| | | | | | | | |
| | | | | | | | |

Mark each task Pass or Fail. Note first-visit wake-up wait separately in the Notes column.

## Sign-off

Tested by: ____________________  Date: ____________  Testers: ____  Overall result (all tasks passed by at least 80% of testers): Yes / No

Signature: ____________________
