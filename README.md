# Daikin One for Home Assistant

![GitHub release (latest by date)](https://img.shields.io/github/v/release/zlangbert/ha-daikinone?style=flat-square) [![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

A custom component for Home Assistant to integrate with Daikin One+ smart HVAC systems. This integration allows you to control your thermostats and view all the telemetry reported by your equipment.

- [Daikin One for Home Assistant](#daikin-one-for-home-assistant)
  - [Features](#features)
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

- Controllable climate entities for each thermostat
- Native Daikin Auto with its single target temperature, plus an emulated Heat/Cool range mode
- All HVAC modes supported by the Daikin One+ system, including Emergency Heat
- Intelligent handling of thermostat updates for ultra-fast response times
- Sensors for status, temperatures, airflow, demand, etc. for all connected equipment
- Automatically discovered outdoor heat-pump devices with instantaneous power and cumulative energy sensors
- Outdoor and indoor air quality sensors (if reported by your system)

### Mini-split heat-pump grouping and energy

For multi-head mini-split systems, Daikin reports outdoor-unit telemetry through each connected indoor head but does
not expose an outdoor-unit serial number. The integration compares the reported outdoor telemetry once, creates a
stable heat-pump grouping, and then stores that grouping so changing readings cannot move entities between devices.

Each discovered heat pump exposes **Power** in watts and **Energy consumption** in kWh. The energy value is an
estimated cumulative counter reported by Daikin and can be selected as an electricity source in Home Assistant's
Energy dashboard.

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

<!-- markdownlint-disable-next-line no-inline-html -->
<img src="docs/dashboard.png" width="350" alt="dashboard example">

Dashboard source can be found [here](docs/dashboard.yaml) if you'd like you use it as a starting point for your own dashboard.

## Todo

- Weather entities for each thermostat
- Support for additional equipment types

## Supported Equipment

The following is the list of currently confirmed working equipment.

If you have a Daikin One+ system and your equipment is not listed here, please open an issue and we can work on adding support. Your raw Daikin API data can be retrieved by clicking "Download Diagnostics" on a thermostat's device page in Home Assistant. That information will be required to add support for your equipment.

### Thermostats

- One Touch Smart Thermostat

### Air Handlers

- [MBVC Modular Blower](https://daikincomfort.com/products/heating-cooling/whole-house/air-handlers-coils/mbvc-modular)

### Heat Pumps

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
