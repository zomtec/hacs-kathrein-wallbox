# AGENTS.md

Binding rules for AI agents working on this repository. They take precedence over
default agent behavior. When a rule conflicts with a user request, say so and ask.

## 1. Project overview

Custom Home Assistant integration (HACS) for Kathrein Wallboxes, communicating over
Modbus TCP. Domain: `kathrein_wallbox`, `iot_class: local_polling`, depends on the core
`modbus` integration and the `modbus_connection` library.

| Path | Responsibility |
|------|----------------|
| `custom_components/kathrein_wallbox/__init__.py` | Entry setup/unload, service registration |
| `coordinator.py` | `DataUpdateCoordinator`, the only place that polls the device |
| `model.py` | Register definitions (`modbus_connection` components), decoding, enums |
| `entity.py` | Shared base entity (`unique_id`, `device_info`) |
| `sensor.py`, `binary_sensor.py` | Entity descriptions and platform setup |
| `config_flow.py` | Setup, validation and reconfigure flow |
| `const.py` | Constants and defaults |
| `diagnostics.py` | Redacted diagnostics download |
| `services.yaml`, `strings.json`, `icons.json`, `translations/` | Service, UI text and icon metadata |
| `modbus_register/Modbus-Server.md` | Source of truth for the register map |
| `tests/` | pytest suite (no real hardware) |

## 2. Working rules

- Read the affected code and its tests before changing anything.
- Make the smallest change that solves the task. No drive-by refactoring, renaming,
  reformatting of untouched code, or unrequested features.
- Follow existing patterns in this repository before introducing new ones.
- Fix root causes. Do not add workarounds, retries, or broad `try/except` to hide a
  problem.
- Never guess register addresses, scaling, or device behavior. Check
  `modbus_register/Modbus-Server.md`; if it is not covered there, ask.
- **Ask the user before** any of the following, and wait for the answer:
  - architectural changes (new modules, new patterns, restructuring);
  - adding, removing, or bumping dependencies or `requirements`;
  - breaking changes: `domain`, `unique_id` format, entity keys, service names or
    schemas, config entry data layout, stored state;
  - raising the minimum Home Assistant version in `hacs.json`;
  - changing `.github/workflows/`, `hacs.json`, or `ruff.toml`.
- When requirements are ambiguous, ask instead of assuming.

## 3. Home Assistant rules

Orientation: the Home Assistant
[Integration Quality Scale](https://developers.home-assistant.io/docs/core/integration-quality-scale/)
(Bronze, then Silver). It is a guide, not a hard gate.

- **Data flow:** all device I/O goes through the coordinator. Entities only read
  `coordinator.data`; they never poll or talk to the device on their own.
- **Runtime state:** store it in `entry.runtime_data` (typed config entry). Do not use
  `hass.data[DOMAIN]`.
- **Async only:** no blocking calls in the event loop. Use `async_*` APIs; if a blocking
  call is unavoidable, use `hass.async_add_executor_job`.
- **Errors:**
  - coordinator update failure: `UpdateFailed`;
  - setup that may succeed later: `ConfigEntryNotReady`;
  - invalid user input in services: `ServiceValidationError`;
  - device or communication failure in services: `HomeAssistantError`.
  - Catch specific exceptions only. Never `except Exception` unless it is a documented
    boundary.
- **Entities:**
  - `_attr_has_entity_name = True`, `translation_key` for names, no hardcoded names;
  - set `device_class`, `state_class`, `native_unit_of_measurement`, and
    `entity_category` where applicable;
  - derive `unique_id` from the device serial and a stable key. Never change it.
  - Prefer declarative entity descriptions over per-entity subclasses.
- **Availability:** reflect real device state (`available`). Optional components (e.g.
  the energy meter) must not break the rest of the device.
- **Config flow:** validate by actually reading the device, abort on duplicates via
  `unique_id`, support reconfigure, and use error keys from `strings.json`.
- **Services:** declare them in `services.yaml` with a voluptuous schema and
  translatable descriptions. Validate input before writing registers.
- **Diagnostics:** redact serial numbers, host, and other identifying data.
- **Logging:** use `_LOGGER` with lazy `%s` formatting, no f-strings, no `print`. Log
  state transitions once (e.g. "became unavailable"), not on every poll.
- **Storage:** never persist secrets or personal data in logs, diagnostics, or tests.

## 4. Modbus and domain rules

- Register addresses, types, scaling, and units live in `model.py` only. Platforms and
  services consume decoded properties and constants, not raw addresses.
- Writable register addresses used by services belong in named constants, not literals
  scattered across the code.
- Keep the supported mapping version (`0x0002`) check in the config flow. A new mapping
  version requires updating `modbus_register/Modbus-Server.md` and asking the user.
- Document units and scaling of every register where it is defined.

## 5. Code quality

- Python 3.14, full type annotations for all functions, methods, and attributes. Use
  `X | None`, built-in generics, and `from __future__ import annotations` only where
  needed.
- Ruff is the single source of formatting and lint rules (`ruff.toml`). Do not reformat
  by hand or add `# noqa` / `# type: ignore` without a one-line reason.
- Naming: `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants. Private
  helpers start with `_`. Home Assistant callbacks follow HA naming (`async_*`).
- Keep functions small and single-purpose. Extract duplicated logic instead of copying
  blocks; do not create abstractions for a single use.
- No magic numbers or repeated string literals. Put them in `const.py` or a named
  constant next to their only usage.
- No dead code, commented-out code, unused parameters, or leftover debug output.
- Prefer clear data structures (dataclasses, enums, mappings) over long `if/elif` chains.
- Keep imports at module top, grouped by Ruff's isort ordering. No wildcard imports.
- No new third-party dependency without asking (see section 2).

## 6. Comments and documentation

- Code should explain itself through names and structure. Comment only what the code
  cannot show: why, hardware quirks, protocol constraints, non-obvious decisions.
- Keep comments to one short line. No multi-paragraph comments, no restating the next
  line, no change-log or "fixed X" comments, no TODOs without an owner and context.
- Every module, public class, and public function has a concise docstring (imperative
  or descriptive, one line where possible). Tests are exempt.
- Language of code, comments, docstrings, commit-style text, and README is English.
- User-visible behavior changes (entities, services, options, requirements) must be
  reflected in `README.md`.

## 7. Translations and metadata

- No hardcoded user-facing text in Python. Use `strings.json` and `translation_key`.
- `strings.json` and `translations/en.json` are the reference. Every new or changed key
  must be mirrored in all files in `translations/` (cs, da, de, en, es, fr, it, nb, nl,
  pl, pt, sv). Missing translations are not acceptable; provide proper translations.
- Translations must use the established EV charging and electrical engineering
  terminology of the target language (e.g. wallbox, phase, relay, charging current,
  active energy), not literal word-for-word translations.
- Keep `services.yaml`, `strings.json`, and `icons.json` consistent with the code
  (service names, fields, selector options, entity translation keys).
- Icons are defined in `icons.json`, not via `_attr_icon`, unless state-dependent logic
  requires it.

## 8. Tests

- Framework: `pytest` with `pytest-homeassistant-custom-component`
  (`asyncio_mode = auto`). Reuse fixtures in `tests/conftest.py`.
- Every behavior change or bug fix comes with a test. A bug fix starts with a failing
  test.
- Never require real hardware or network access. Mock at the Modbus unit level.
- Tests assert behavior (states, raised errors, written registers), not implementation
  details. Keep them small and readable.

Run before declaring work done:

```bash
ruff check .
ruff format --check .
python -m pytest
```

## 9. Release and HACS

- `manifest.json` keeps `"version": "0.0.0"`. Never edit it manually and never
  increment it.
- The version is set by `.github/workflows/release.yml` when a GitHub release is
  published: it writes the release tag into `manifest.json` inside the build and
  attaches `kathrein_wallbox.zip` to the release.
- `hacs.json` points to that asset (`zip_release: true`,
  `filename: kathrein_wallbox.zip`). Do not change these values without asking.
- `.github/workflows/validate.yml` runs Ruff, pytest, HACS validation, and hassfest.
  Changes must keep all of them green, including `hassfest` rules for `manifest.json`.

## 10. Definition of done

A task is finished only if all of these hold:

- [ ] The change is minimal and addresses exactly what was requested.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `python -m pytest` passes and new behavior is covered by tests.
- [ ] No hardcoded UI text; all 12 translation files are consistent.
- [ ] `services.yaml`, `strings.json`, `icons.json`, and `README.md` match the code.
- [ ] No new dependency, breaking change, or workflow change without prior approval.
- [ ] `manifest.json` version is still `0.0.0`.
- [ ] No dead code, debug output, or unexplained `noqa` / `type: ignore`.

## 11. Anti-patterns (do not do these)

- Quick fixes that "work" but bypass the coordinator, entity model, or config flow.
- Probing for several possible method names or signatures instead of using the
  documented API. If an API behaves unexpectedly, ask before adding a workaround.
- Copy-pasting near-identical entity, service, or test blocks instead of
  parametrizing or sharing a helper.
- Swallowing errors, returning `None` silently, or logging and continuing on failures
  that make data invalid.
- Changing `unique_id`, entity keys, or service schemas to "clean up".
- Adding comments, docstrings, or abstractions to look thorough.
