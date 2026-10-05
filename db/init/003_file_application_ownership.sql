Next, save the fix for GitHub:
1. Open the Query Tool’s Save As option.
2. Save only the migration block—from BEGIN through COMMIT, not the earlier queries or tests.
3. Use the filename 003_file_application_ownership.sql in your project’s db/init folder.
This lets a fresh Docker database receive the same fix automatically. Existing databases will need to run this migration once, as you just did.