# Local Supabase Auth canary

Run `python3 scripts/supabase-local-auth-canary.py`. The runner starts the pinned local
configuration, creates one confirmed operator through the local admin endpoint, executes
the same Auth checks as the hosted canary, deletes the operator, and stops the stack.

Local generated keys remain in process memory and are never printed or passed in command
arguments. This test proves application behavior, not hosted Management API or provider
compatibility; the ephemeral hosted release gate remains mandatory.
