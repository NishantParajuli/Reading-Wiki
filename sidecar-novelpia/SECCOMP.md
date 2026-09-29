# Chromium sandbox syscall profile

`seccomp_profile.json` vendors Docker/Moby's default profile from
[moby/profiles commit 85e237f1fe229a0c61c9c7d8e743fa780d3b97ca](https://github.com/moby/profiles/blob/85e237f1fe229a0c61c9c7d8e743fa780d3b97ca/seccomp/default.json).
Moby profiles are licensed under Apache-2.0.

The only local change is an initial allow rule for `clone`, `setns`, `unshare`,
and `chroot`. The first three follow Playwright's Chromium sandbox requirements.
`chroot` must also pass seccomp after Chromium creates its own user namespace;
the kernel still enforces its namespace capability checks. The container remains
non-root, drops all container capabilities, and enables `no-new-privileges`.
Chromium runs with its sandbox enabled. This does not grant `SYS_ADMIN` or use an
unconfined seccomp policy.

The older profile shipped with Playwright v1.61.1 predates modern Docker runtime
syscalls and failed during container startup on the deployment host. Keep the
Moby baseline current when upgrading the container runtime, retaining only this
documented Chromium rule and verifying a sandboxed browser launch.
