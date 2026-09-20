# Daikin One for Home Assistant

![GitHub release (latest by date)](https://img.shields.io/github/v/release/zlangbert/ha-daikinone?style=flat-square) [![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)

Daikin One for Home Assistant lets you control supported Daikin thermostats and mini-split heads from Home Assistant.
It also shows temperatures, power use, energy use, and other data from your system.

- [Daikin One for Home Assistant](#daikin-one-for-home-assistant)
  - [Features](#features)
    - [Configure menu](#configure-menu)
    - [Mini-split heat-pump grouping, power, and energy](#mini-split-heat-pump-grouping-power-and-energy)
    - [How Heat/Cool works](#how-heatcool-works)
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

- Control Daikin One thermostats and supported mini-split heads.
- Choose Off, Heat, Cool, Auto, or Heat/Cool. Emergency Heat is shown only on systems that have backup heat.
- Set the fan to Auto, Quiet, Low, Medium Low, Medium, Medium High, or High.
- Set supported vertical vanes to Fixed or Oscillate.
- Use a separate room sensor for temperature and humidity.
- Group indoor heads that share one outdoor heat pump.
- See current power use in watts and total energy use in kWh.
- Control air circulation on systems that support it.
- See useful system data, such as temperatures, airflow, compressor use, and air quality.
- Download details that can help when you need support.

### Configure menu

Open **Settings → Devices & services → Daikin One → Configure**. This is the cogwheel menu.

You can move between the pages without losing your work. Nothing is saved until you choose **Save changes**.

- **Edit a heat pump** lets you rename a heat-pump group or change which indoor heads belong to it. You can also
  delete the group. Deleting it also removes its power and energy sensors from Home Assistant.
- **Add a heat pump** groups the indoor heads that share one outdoor unit. Give the group a name and pick its indoor
  heads. A head can be in only one group. All heads in a group must be in the same Daikin location. The integration
  chooses the best head to supply the group's energy reading.
- **Emulated Heat/Cool settings** has three settings that apply to all heads:
  - **Temperature tolerance** says how far the room may move past a target before heating or cooling starts. You can
    choose 0–5 °C. The default is 0.5 °C.
  - **Minimum direction time** says how long a shared outdoor unit must wait before changing from heating to cooling,
    or from cooling to heating. You can choose 0–120 minutes. The default is 15 minutes.
  - **Convert external Daikin Auto to emulated Heat/Cool** controls what happens when you choose Auto in the Daikin
    app or on a Daikin remote. When this is on, Home Assistant changes that choice to its own Heat/Cool mode. This is
    off by default.
- **External temperature sensors** lets you set up one indoor head at a time:
  - **Temperature sensor** is the room sensor that Home Assistant will use. It is required.
  - **Humidity sensor** adds the room humidity to the thermostat card. It is optional.
  - **Maximum setpoint bias** limits how much Home Assistant may change the temperature sent to the Daikin head. The
    thermostat card still shows the temperature you chose. You can choose 0.5–10 °C in 0.5 °C steps. The default is
    5 °C.
  - **Disable external temperature control** stops using the room sensor for that head. This does not turn the Daikin
    schedule back on.
- **Save changes** saves all changes and reloads the integration.

### Mini-split heat-pump grouping, power, and energy

Some mini-split systems have several indoor heads connected to one outdoor heat pump. Daikin sends the outdoor
unit's readings through the indoor heads, but does not tell us the outdoor unit's serial number. The integration
compares those readings to work out which heads share a heat pump. It then saves the group so it does not change by
mistake later.

Each heat-pump group gets two sensors:

- **Power** shows how much power the heat pump is using now, in watts.
- **Energy consumption** shows Daikin's running estimate of total energy use, in kWh. You can add this sensor to the
  Home Assistant Energy dashboard.

If the integration is not sure which heads belong together, the heads will still work. Home Assistant will show a
repair notice. Use the **Configure** menu to add or fix the group.

### How Heat/Cool works

Heads that can heat and cool have two automatic choices:

- **Auto** is controlled by Daikin. It uses one target temperature.
- **Heat/Cool** is controlled by this integration. You set a low temperature for heat and a high temperature for
  cooling. The integration chooses Heat, Cool, or Off as the room changes.

**Emergency Heat** is shown only when Daikin says the system has backup heat. It uses backup heating instead of the
heat pump. It is not shown on normal mini-split heads.

All heads on one outdoor heat pump must heat or cool together. If different rooms ask for different things, the room
that is furthest from its target chooses the direction. The temperature tolerance and wait time help stop the system
from changing direction too often.

Choosing Heat, Cool, Auto, or Off by hand takes control away from Heat/Cool mode. This includes choices made with a
Daikin remote or app. You may turn on **Convert external Daikin Auto to emulated Heat/Cool** if you want an Auto
choice from the Daikin app or remote to start Home Assistant's Heat/Cool mode instead.

### Optional external room temperature

You can use a Home Assistant room sensor instead of the sensor inside a Daikin head. Open **Configure**, choose
**External temperature sensors**, choose the head, and then choose a temperature sensor. You can also choose a
humidity sensor.

The sensor inside a head can warm up or cool down faster than the rest of the room. To handle this, Home Assistant
may send a different target to the head than the target shown on the thermostat card. It learns one adjustment for
heating and another for cooling.

The adjustment changes by 0.5 °C only when the room has stayed more than 0.3 °C from the target for 15 minutes. It
keeps learning while the feature is on, so it can follow changes in the room or the seasons. The **Maximum setpoint
bias** limits the adjustment. The default limit is 5 °C.

This lets the heat pump keep changing its output smoothly. Home Assistant does not simply turn it fully on and off.
The adjustment works in Heat, Cool, and Home Assistant's Heat/Cool mode. It does not work in Daikin Auto or Emergency
Heat.

Home Assistant turns off the head's Daikin schedule while this feature is on. If you change the target with a Daikin
controller or remote, Home Assistant uses that as the new target.

The thermostat card shows the room sensor's temperature and humidity even when the head is off. If a reading is bad,
missing, or more than 30 minutes old, Home Assistant falls back to the sensor inside the head. Learning pauses until
the room sensor works again. Turning off external temperature control removes the adjustment, but does not turn the
Daikin schedule back on.

### Fan and vane controls

On supported indoor heads, **Fan mode** sets the blower speed. The choices are Auto, Quiet, Low, Medium Low, Medium,
Medium High, and High.

Daikin remembers a different fan speed for Heat, Cool, and Auto. Changing the speed in one mode does not change the
others. Home Assistant's Heat/Cool mode uses the same chosen speed for both heating and cooling. You can still change
it while the room does not need heating or cooling.

Fan mode is hidden when the head is set to Off. Some whole-home systems also have separate **Circulation Mode** and
**Circulation Speed** controls. These appear only when the system supports them. They are separate from the fan speed
used while heating or cooling.

Supported mini-split heads also have **Swing mode** for the vertical vane:

- **Fixed** keeps the vane in one position.
- **Oscillate** moves the vane up and down.

Daikin remembers a different vane choice for Heat, Cool, and Auto. Home Assistant's Heat/Cool mode uses the same
choice for heating and cooling. Swing mode is hidden when the head is Off. It is also hidden if the head does not
support this control.

### Diagnostics

Use **Download diagnostics** on the Daikin One integration page or on a device page. This file gives a support person
details about your Daikin system and this integration.

The integration file covers all devices. A device file covers only that device. If you use a separate room sensor,
the file also includes its current temperature and humidity, the learned heating and cooling adjustments, the targets
used by Home Assistant and Daikin, and the time of the last update.

<!-- markdownlint-disable-next-line no-inline-html -->
<img src="docs/dashboard.png" width="350" alt="dashboard example">

Dashboard source can be found [here](docs/dashboard.yaml) if you'd like to use it as a starting point for your own dashboard.

## Todo

- Weather entities for each thermostat
- Support for additional equipment types

## Supported Equipment

The equipment below is known to work.

If your Daikin One+ equipment is not listed, please open an issue. We can work with you to add support. We will need
a diagnostics file from the device page in Home Assistant. Choose **Download diagnostics** to get it.

### Thermostats

- One Touch Smart Thermostat
- Daikin One Home-connected mini-split indoor heads. Home Assistant shows only the controls that each head supports.

### Air Handlers

- [MBVC Modular Blower](https://daikincomfort.com/products/heating-cooling/whole-house/air-handlers-coils/mbvc-modular)

### Heat Pumps

- Multi-head mini-split outdoor units that send the same outdoor readings through their indoor heads
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

You must [install HACS](https://hacs.xyz/docs/installation/prerequisites) first.

1. Open HACS from the Home Assistant sidebar.
2. Open **Integrations**.
3. Select the three dots in the top-right corner. Then choose **Custom repositories**.
4. Paste `https://github.com/zlangbert/ha-daikinone` into **Add custom repository URL**. Choose **Integration** as
   the category.
5. Select **Add**.
6. Restart Home Assistant.
7. Select the button below to add the integration and start setup.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=daikinone)

### Manual Install

Manual installation is for people who are comfortable using SSH and the Linux command line. HACS is easier and safer.

1. Download or clone this repository.
2. Copy the `custom_components/daikinone` folder into the `custom_components` folder in Home Assistant.
3. Restart Home Assistant.
4. Select the button below to add the integration and start setup.

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=daikinone)
