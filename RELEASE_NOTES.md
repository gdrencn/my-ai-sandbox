# Stable 0.2.25

Promotes the accepted v0.2.25 product and installer with identical bytes and numeric version. Preferences adds About my-ai-sandbox, showing the running product version and a Back choice through the shared page component. Both languages and Enter/Right/Escape/Left navigation preserve parent focus. CLI --version remains available.

The release branch advances from stable/0.2.24 by one stable-publication commit and retains only product/installer/shared-build source and relevant documentation. Stable assets are mas.pyz, mas-install.pyz and SHA256SUMS. Automated verification uses the unchanged, exactly paired v0.2.25 tester from its test release.

Installation reads source from release and product/installer assets from the selected stable release. Current test verification, user acceptance, stable publication checks and measured scope are recorded on main in IMPLEMENTED.md and TEST_COVERAGE.md.

# Stable 0.2.24

Promotes the accepted v0.2.24 product and installer without changing their bytes or numeric version. This stable version includes fixed container isolation, explicit legacy migration, GPU access and switching, the network switch, the 25-package Ubuntu APT development environment, independent filesystem mounts, standard lifecycle coordination and shared inline menus with corrected resize handling.

The release branch contains stable product/installer source and shared build/installation files. Stable assets are mas.pyz, mas-install.pyz and SHA256SUMS. Automated tests are supplied separately by the immutable v0.2.24 test release.

Installation reads source only from release and product/installer assets from the selected stable release. Matching stable verification and detailed measured limits are recorded on main in IMPLEMENTED.md and TEST_COVERAGE.md.
