# Instructions

1. start a new claude session
2. rename the session to ‘`database setup`’
3. Pull the most recent code - `git pull origin main`
4. Create and switch to a new branch - `git checkout -b feature/database-setup`
5. Create Spec document manually
6. Review the spec document
7. Save the spec document in `.claude/specs` folder by the name of `01-database-setup.md`
8. Enter Plan mode and create a plan based on the spec document
    
    Read `.claude/specs/01-database-setup.md` and the existing `database/db.py` and `app.py`, then generate an implementation plan.Save this plan to `.claude/plans/01-database-setup.md`
    
9. Implement the plan - review edits manually
10. Validate the implementation against the spec document
11. Iterate if required
12. commit the changes 
    
    `git add .`
    
    `git commit -m ‘database setup’`
    
13. Push the code to Github - `git push origin feature/database-setup` 
14. Create and merge the PR
15. Checkout to the main branch - `git checkout main`
16. Delete the feature branch - `git branch -D feature/database-setup`