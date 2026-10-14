# Pump Station PS-3 Control Narrative

Revision B, issued for review. This narrative describes how the PLC controls the three
transfer pumps at PS-3, the interlocks that protect them, and the alarms the operator sees.

## Scope

The narrative covers the duty/assist/standby pump set, the wet-well level control loop and
the interface to the site SCADA. Chemical dosing is covered in a separate document.

<!-- RC#JB-1 Josephine Bloggs 2026-10-12 | Scope should say which SCADA tags are published; the integrator asked twice. -->
<!-- RC#ML-1 Mark Lazarides 2026-10-13 re JB-1 | Agreed. Tag list added as Appendix A in Rev C. -->
<!-- RC#JB-1 resolved Josephine Bloggs 2026-10-13 | Appendix A covers it. -->

## Operating modes

| Mode | Selected by | Behaviour |
|------|-------------|-----------|
| Auto | SCADA or local selector | Duty pump follows wet-well level; assist cuts in at high level |
| Manual | Local selector only | Operator starts and stops pumps; level alarms still active |
| Maintenance | Key switch on panel | Pump isolated from automatic control, interlocks still enforced |

<!-- RC#JB-2 Josephine Bloggs 2026-10-12 | Does Maintenance mode also inhibit the remote SCADA start? The table implies it but does not say. -->
<!-- RC#ML-2 Mark Lazarides 2026-10-13 re JB-2 | It does. I will make it explicit in the Behaviour column and in 4.3 of the FDS. -->

## Interlocks

!!! warning "Hard-wired interlocks take priority"
    The dry-run and high-motor-temperature interlocks are hard-wired through the starter
    control circuit. The PLC monitors them but cannot override them.

    <!-- RC#JB-3 Josephine Bloggs 2026-10-12 | Confirm the thermistor relay model. The panel schedule still shows the superseded part. -->

The PLC enforces the soft interlocks below. Each one inhibits a start and, where stated, trips
a running pump.

- Low wet-well level: inhibit start, trip after 10 s below the stop level
- Discharge valve not open: inhibit start
- Starter not healthy: inhibit start and trip

## Alarms

Alarms are raised to SCADA with the priority shown and are latched until acknowledged at
the panel or from SCADA.

| Alarm | Priority | Auto-reset |
|-------|----------|------------|
| Wet well high-high | Critical | No |
| Pump trip | High | No |
| Pump runtime exceeded | Low | Yes |

## Open points

- Confirm the duty-rotation interval with the operator before Rev C.
- Spare I/O allocation is to be agreed with the panel builder.
