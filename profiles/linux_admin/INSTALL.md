# linux_admin Profile — Install Instructions

These notes describe how `bootstrap.sh` installs the **linux_admin**
specialist Profile on the AIAMSBS host. Customers do not run this by
hand; `bootstrap.sh --profile linux_admin` (or `--profile all`) does it.

## Source layout (in the AIAMSBS repo)

- `profiles/linux_admin/SOUL.md`     — persona (runtime identity)
- `profiles/linux_admin/SKILL.md`    — skill routing map
- `profiles/linux_admin/INSTALL.md`  — this file
- `profiles/linux_admin/skills/`     — skill implementations (BACKLOG #16, future)

After `bootstrap.sh` runs, the runtime sees
`~/.hermes/profiles/linux_admin/{SOUL.md,SKILL.md}` (in multi-profile
mode; mirrors `install_default_profile_soul`'s layout-auto-detect at
bootstrap.sh lines ~441–470).

## Suggested bootstrap.sh wiring

### New CLI flag

Add to the `while [[ $# -gt 0 ]]` parser:

```
--profile NAME    Install a specialist profile: linux_admin, network_admin,
                  windows_admin, vsphere_admin, all. Multiple flags OK.
                  Implies multi-profile layout at $HERMES_HOME/profiles/.
                  Default (no flag): install default Profile only.
```

### Suggested function name

`install_linux_admin_profile_soul()` — mirrors
`install_default_profile_soul()` for naming consistency. It:

1. Creates `$HERMES_HOME/profiles/linux_admin/`.
2. Copies `SOUL.md` + `SKILL.md` from `$INFRA_DIR/profiles/linux_admin/`
   into `$HERMES_HOME/profiles/linux_admin/`.
3. Logs `[SUCCESS] linux_admin Profile installed at …`.
4. Skips silently if the source files are not present in `$INFRA_DIR`
   (same `log_warn` + `return 0` pattern as the default installer).
5. Optionally pulls the ansible container when BACKLOG #15 ships —
   gated on a separate `--with-ansible` flag, off by default today.

### Wire into `main()`

After `install_default_profile_soul` (line ~1281), call
`install_linux_admin_profile_soul` if the customer passed
`--profile linux_admin` or `--profile all`. Same conditional pattern
as `if [ "$AUTO_DEPLOY" = true ]`.

## Should this live in bootstrap.sh or a separate script?

**Recommendation: keep it in bootstrap.sh.** Reasoning:

- `install_default_profile_soul()` already established the pattern;
  splitting a sibling into a separate script breaks parallelism for
  no benefit.
- Customers run `bootstrap.sh` exactly once per install; a separate
  `register_specialist_profile.sh` adds a "now run this other thing"
  step that breaks the "one command, done" UX.
- Specialists #17–19 (network_admin, windows_admin, vsphere_admin) all
  follow the same shape — a single function each inside bootstrap.sh
  scales better than five standalone scripts.

**Future evolution:** if the install grows to need an ansible
container (BACKLOG #15), a separate `install_linux_admin_ansible.sh`
(called from `install_linux_admin_profile_soul` when `--with-ansible`
is set) is fine — but the SOUL/SKILL copy step stays in bootstrap.sh.

## E2E verification

After bootstrap finishes, confirm the linux_admin Profile is active:

1. **Files in place**
   ```
   ls -la ~/.hermes/profiles/linux_admin/
   # expect: SOUL.md, SKILL.md
   ```

2. **Hermes sees the Profile**
   ```
   hermes profile list
   # expect: a row named "linux_admin" alongside "default"
   ```

3. **Routing works.** In the Hermes chat, ask:
   > "linux_admin, what's the latest kernel on web-01?"
   The default Profile should route to linux_admin. If linux_admin
   doesn't respond, the Profile is not registered — re-run
   `install_linux_admin_profile_soul` from bootstrap.sh.

4. **(Optional) Ansible container.**
   ```
   docker ps | grep ansible
   ```
   Empty result is expected today (BACKLOG #15 not shipped). When it
   ships, the container appears after `--profile linux_admin --with-ansible`.

## Version

- **v1.0** — 2026-06-25 (design)
- See `~/AIAMSBS/BACKLOG.md` #16