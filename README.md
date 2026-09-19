# Daikin One for Home Assistant

![GitHub release (latest by date)](https://img.shields.io/github/v/release/zlangbert/ha-daikinone?style=flat-square) [![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A custom component for Home Assistant to integrate with Daikin One+ smart HVAC systems. This integration allows you to control your thermostats and view all the telemetry reported by your equipment.

- [Daikin One for Home Assistant](#daikin-one-for-home-assistant)
  - [Features](#features)
    - [Configure menu](#configure-menu)
    - [Mini-split heat-pump grouping, power, and energy](#mini-split-heat-pump-grouping-power-and-energy)
    - [Emulated Heat/Cool](#emulated-heatcool)
    - [Optional external room temperature](#optional-external-room-temperature)
    - [Fan and vane controls](#fan-and-vane-controls)
    - [Diagnostics](#diagnostics)
  - [Todo](#todo)
  - [Supported Equipment](#supported-equipment)
    - [Thermostats](#thermostats)
    - [Air Handlers](#air-handlers)
    - [Heat Pumps](#heat-pumps)
    - [Air Conditioners](#air-conditioners)
    - [Furnaces](#furnaces)
  - [Installation](#installation)
    - [Install via HACS](#install-via-hacs)
    - [Manual Install](#manual-install)

## Features

- Climate entities for Daikin One thermostats and compatible mini-split indoor heads
- Heat, Cool, Off, native Daikin Auto, and coordinated emulated Heat/Cool; Emergency Heat appears only when the
  equipment reports an auxiliary heat source
- Mode-specific operating fan speeds: Auto, Quiet, Low, Medium Low, Medium, Medium High, and High
- Capability-detected vertical vane control with Fixed and Oscillate swing modes
- Optional external room temperature and humidity display with continuously learned heating and cooling setpoint
  bias
- Automatic or manually managed multi-head heat-pump grouping, with live power consumption in watts and cumulative
  energy consumption in kWh
- Separate circulation mode and speed controls on unitary systems that report those capabilities
- Equipment telemetry for temperatures, airflow, demand, compressor operation, power, and other reported values
- Outdoor and indoor air-quality sensors when reported by the equipment
- Downloadable integration and device diagnostics, including external-sensor readings and adaptive-control state

### Configure menu

Open **Settings → Devices & services → Daikin One → Configure** (the cogwheel menu). Changes are staged while you
move between menu pages and are saved when you select **Save changes**.

- **Edit a heat pump** appears when at least one heat-pump group exists. Select a group to change its name or
  connected indoor heads, or enable **Delete this heat pump** to remove it. Removing a group also removes that
  group's power and energy entities.
- **Add a heat pump** creates a named outdoor-unit group and assigns its indoor heads. A head can belong to only one
  group, and every head in a group must be in the same Daikin location. The integration automatically selects the
  member with the best cumulative-energy telemetry as the group's energy source.
- **Emulated Heat/Cool settings** contains three global controls:
  - **Temperature tolerance** sets the distance from a target before a head requests heating or cooling. Range:
    0–5 °C; default: 0.5 °C.
  - **Minimum direction time** prevents a shared outdoor unit from switching between heating and cooling too
    quickly. Range: 0–120 minutes; default: 15 minutes.
  - **Convert external Daikin Auto to emulated Heat/Cool** determines whether selecting Auto from a Daikin remote or
    app is adopted as Home Assistant's emulated range mode. It is disabled by default.
- **External temperature sensors** first asks which indoor head to configure, then provides:
  - **Temperature sensor**, a required Home Assistant sensor with the temperature device class.
  - **Humidity sensor**, an optional Home Assistant sensor with the humidity device class.
  - **Maximum setpoint bias**, the largest difference Home Assistant may apply between the displayed logical target
    and the physical target sent to Daikin. Range: 0.5–10 °C in 0.5 °C steps; default: 5 °C.
  - **Disable external temperature control**, shown for an already configured head. Disabling restores unbiased
    logical heat and cool targets but does not automatically re-enable the Daikin schedule.
- **Save changes** persists every staged grouping, emulation, and external-sensor setting and reloads the integration.

### Mini-split heat-pump grouping, power, and energy

For multi-head mini-split systems, Daikin reports outdoor-unit telemetry through each connected indoor head but does
not expose an outdoor-unit serial number. The integration compares the reported outdoor telemetry once, creates a
stable heat-pump grouping, and then stores that grouping so changing readings cannot move entities between devices.

Each discovered outdoor heat pump exposes two consumption entities:

- **Power** is the current power consumption in watts and can be used for live monitoring and automations.
- **Energy consumption** is Daikin's estimated cumulative consumption in kWh. It uses Home Assistant's
  `total_increasing` state class and can be selected as an electricity source in the Energy dashboard.

If automatic discovery is uncertain, the affected heads remain fully functional and Home Assistant raises a repair
notice. Open the Daikin One integration's **Configure** dialog to add, rename, remove, or correct heat-pump groups.
Each indoor head can belong to only one heat pump.

### Emulated Heat/Cool

For heads that support both heating and cooling, Home Assistant exposes two
distinct automatic modes:

- **Auto** is Daikin's native mode and uses one target temperature.
- **Heat/Cool** is managed by this integration and uses Home Assistant's low and
  high target temperatures. The head is switched between Heat, Cool, and Off as
  needed.

**Emergency Heat** is exposed as a preset only when Daikin explicitly reports an
auxiliary heat source. It bypasses normal compressor heating and uses auxiliary
heating elements, so it is intended for equipment that actually supports that
mode rather than for normal mini-split operation.

Heads connected to the same outdoor heat pump are coordinated. The room furthest
outside its configured range selects the outdoor unit's direction, with a
configurable hysteresis and minimum direction time to reduce cycling. Explicit
Heat, Cool, or native Auto commands take priority; incompatible emulated heads
remain off and show their reason in the `emulation_status` attribute. Home
Assistant also shows a temporary notification while manual control suspends an
emulated head.

The integration options configure the global temperature tolerance, minimum
direction time, and whether an Auto selection made outside Home Assistant should
be converted to emulated Heat/Cool. External Auto conversion is disabled by
default. Physical remote Heat, Cool, and Off commands leave emulated mode and are
respected after the integration has distinguished them from a recently sent
cloud command.

### Optional external room temperature

The integration can use any Home Assistant temperature sensor as the room
temperature for an individual head. Open the integration's **Configure** dialog,
choose **External temperature sensors**, select the head and sensor, and set the
maximum allowed bias. The default maximum is 5 °C. You can also select an
optional humidity sensor, since Home Assistant normally exposes temperature and
humidity from the same physical device as separate entities.

In Heat, Cool, and emulated Heat/Cool, Home Assistant keeps showing the desired
logical target. The integration slowly learns a separate heating and cooling
bias and sends a different physical target to the Daikin head. It adjusts by
0.5 °C only after the room remains more than 0.3 °C from target for 15 minutes,
and keeps relearning while enabled so seasonal or room changes do not leave a
stale calibration. This retains the head's own inverter control instead of
turning it into a binary on/off device. Native Daikin Auto and Emergency Heat
are not adaptively biased.

While enabled, Home Assistant disables that head's native Daikin schedule and
owns its logical target. A target changed on a Daikin controller or remote is
adopted as the new logical target after cloud-command propagation is ruled out.
If the external sensor is unavailable or has not updated for 30 minutes, the
current learned bias and physical target are frozen and Home Assistant falls
back to displaying and using the head's internal temperature. Removing the
external-sensor configuration restores the unbiased logical heat and cool
targets; it does not re-enable the Daikin schedule automatically.

Fresh configured temperature and humidity readings are shown on the climate
entity in every HVAC mode, including Off. Each reading falls back independently
to the head's internal sensor when its external entity is invalid, unavailable,
or stale.

### Fan and vane controls

For compatible indoor heads, the climate entity's **Fan mode** control sets the
actual operating fan speed: Auto, Quiet, Low, Medium Low, Medium, Medium High,
or High. Daikin stores a separate speed for each HVAC mode, so Heat, Cool, and
native Auto change only their own speed. Emulated Heat/Cool applies the selected
speed to both Heat and Cool and remains adjustable while the controller has the
head physically off between calls for heating or cooling.

Native Off hides the operating fan control. If a unitary thermostat reports
Daikin's separate circulation controls, Home Assistant exposes them as
**Circulation Mode** and **Circulation Speed** selects. These selects are not
created for mini-split heads whose API payload does not contain the corresponding
circulation fields.

Compatible mini-split heads also expose **Swing mode** with Fixed and Oscillate
for the vertical vane. Like fan speed, Daikin stores vane behavior separately
for each HVAC mode. Native Heat, Cool, and Auto update their own setting, while
emulated Heat/Cool applies one selection to both Heat and Cool. The control is
hidden in native Off and on heads that do not report vertical-vane fields.

### Diagnostics

Use **Download diagnostics** on either the Daikin One integration entry or an individual device. Integration
diagnostics contain the raw Daikin device data plus an external-control snapshot for every configured head. Device
diagnostics limit that information to the selected device.

External-control diagnostics include the configured temperature and humidity entity IDs, their current valid
readings, maximum bias, controller status, logical targets, learned heating and cooling biases, physical targets,
last evaluation and adjustment times, and whether a physical setpoint was limited. The same current external
temperature, humidity, bias, and physical-target information is available as climate entity attributes while the
feature is configured.

<!-- markdownlint-disable-next-line no-inline-html -->
<img src="docs/dashboard.png" width="350" alt="dashboard example">

Dashboard source can be found [here](docs/dashboard.yaml) if you'd like to use it as a starting point for your own dashboard.

## Todo

- Weather entities for each thermostat
- Support for additional equipment types

## Supported Equipment

The following is the list of currently confirmed working equipment.

If you have a Daikin One+ system and your equipment is not listed here, please open an issue and we can work on adding support. Your raw Daikin API data can be retrieved by clicking "Download Diagnostics" on a thermostat's device page in Home Assistant. That information will be required to add support for your equipment.

### Thermostats

- One Touch Smart Thermostat
- Daikin One Home-connected mini-split indoor heads; available climate, fan, and vane controls are detected from
  each head's reported capabilities

### Air Handlers

- [MBVC Modular Blower](https://daikincomfort.com/products/heating-cooling/whole-house/air-handlers-coils/mbvc-modular)

### Heat Pumps

- Multi-head mini-split outdoor units that report shared outdoor telemetry through their connected indoor heads
- [DZ9VC](https://daikincomfort.com/products/heating-cooling/whole-house/heat-pump/dz9vc)
- [DZ6VS](https://daikincomfort.com/products/heating-cooling/whole-house/heat-pump/daikin-fit-heat-pump-dz6vs)
- [DZ17VSA](https://daikincomfort.com/products/heating-cooling/whole-house/heat-pump/daikin-fit-heat-pump)

### Air Conditioners

- [DX6VS](https://daikincomfort.com/products/heating-cooling/whole-house/air-conditioner/daikin-fit-dx6vs)

### Furnaces

- [DM97MC](https://daikincomfort.com/products/heating-cooling/whole-house/gas-furnaces/dm97mc)
- [DM80VC](https://daikincomfort.com/products/heating-cooling/whole-house/gas-furnaces/dm80vc)

## Installation

### Install via HACS

_HACS must be [installed](https://hacs.xyz/docs/installation/prerequisites) before following these steps._

1. Log into your Home Assistant instance and open HACS via the sidebar on the left.
2. In the HACS console, open **Integrations**.
3. On the integrations page, select the "vertical dots" icon in the top-right corner, and select **Custom repositories**.
4. Paste `https://github.com/zlangbert/ha-daikinone` into the **Add custom repository URL** box and select **Integration** in the **Category** menu.
5. Select **Add**.
6. Restart Home Assistant
7. Click the below button to add the integration and start setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=daikinone)

### Manual Install

_A manual installation is more risky than installation via HACS. You must be familiar with how to SSH into Home Assistant and working in the Linux shell to perform these steps._

1. Download or clone this repository
2. Copy the `custom_components/daikinone` folder from the repository to your Home Assistant `custom_components` folder
3. Restart Home Assistant
4. Click the below button to add the integration and start setup

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=daikinone)
