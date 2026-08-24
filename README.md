# Unofficial 'Mijn Water-Link' Home Assistant Custom Integration

![image](https://github.com/user-attachments/assets/69820796-f96d-44e2-b0c4-0dbd94a06e34)

As Water Link does not expose a proper API, this integration authenticates on ['Mijn Water-link' customer portal](https://portaaldigitalemeters.water-link.be/) using OAuth, and scrapes the water consumption data from there. This may not be very robust, as Water-Link has changed their authentication procedures already a few times. Use this integration at your own discretion.
Water-Link is only available in Antwerp, Belgium, so no point in installing this integration if you are not an existing customer.

## Available Data

This integration will fetch the latest available datapoint as it is present in the 'Mijn Water-link' portal. Typically the water meter seems to take a local measurement around midnight, which is send to the portal the next day around noon (at least on my meter). It can happen that the latest measured values are only send or received after a couple of days. This means that the value which is present in the portal (which is in turn read by this integration) is outdated anywhere from 12 hours to a couple of days. 

|Parameter | Type | Description  |
|--|--|--|
| Total consumption | State | The total volume of consumed water (in m3) as measured by the digital water meter |
| Is Active | Attribute | Whether the meter is active or not (boolean) |
| Latest reading date | Attribute | The date of last reading |
| Has flow limitation | Attribute | Unclear... presumably related to whether the meter is on a budgetting plan or not (boolean) |
| Is up to date | Attribute | Whether the value is up to date (within a day) (boolean)|
| Address | Attribute | Address where the meter is installed |
| Divergent consumption | Attribute | Whether anomalous water consumption (eg. a leak) is detected |
| Days offset | Attribute | How old the last reading is (in days). Set to '1' for a 'recent' measurement. |
| No data permission | Attribute  | Unclear... presumably related to GDPR and/or whether a customer is entitled to see the measured values or not. |

<img width="423"  alt="image" src="https://github.com/user-attachments/assets/12dd6742-10ff-4019-830a-86bae2829834" />

## Daily consumption statistics (correct dates)

Because the portal value can lag behind by a couple of days, the sensor state alone could put several days of accumulated consumption on the wrong date. To fix this, the integration also fetches the **actual usage per day** from the portal and imports it into Home Assistant's long-term statistics on the date the water was really consumed (up to a year of history is backfilled on first run).

This data is available as the external statistic `mijn_waterlink:meter_<meter id>_consumption`. You can:

- Add it as a **water source in the Energy dashboard** (pick it from the statistics list), or
- Chart it with a *Statistics graph* card.

Note: external statistics are not entities, so you won't find it under Devices & Services — look for it in the statistics picker of the Energy dashboard or the Statistics graph card.


## Installation

### HACS

Mijn Water Link is available in [HACS](https://hacs.xyz/) (Home Assistant Community Store).

Use this link to directly go to the repository in HACS

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zheffie&repository=mijn_waterlink)

_or_

1. Install HACS if you don't have it already
2. Open HACS in Home Assistant
3. Search for "Mijn Waterlink"
4. Click the download button. ⬇️


### Manual
Copy the `custom_components/mijn-waterlink` folder to your `configuration` path and restart Home Assistant. Use the add integration UI to set up your device.

## Configuration
|Configuration | Description  |
|--|--|
| Username | The username that you use to login into 'Mijn Water-link' |
| Password| The password that you use to login into 'Mijn Water-link'  |
| Client ID| I'm not even sure if this needs to be configurable. If the present client ID does not work for you, you may have to inspect your own network traffic to 'Mijn Water-link' |
| Meter ID| your 6-digit meter identification number (eg. 123456) You can find this ID in your specific portal URL, eg. https://portaaldigitalemeters.water-link.be/water-meter/XXXXXX|

## Options
|Option| Description  |
|--|--|
| update_interval | The polling interval to fetch the reading from the Portal. Default is set to 2700s (2 hours). Note that the digital water meter only sends an update once a day |

## Development & testing

Install the test dependencies and run the unit tests (no credentials needed):

```bash
pip install -r requirements_test.txt
pytest
```

There is also a live test suite that exercises the real 'Mijn Water-link' portal (authentication, meter data, and the daily measurements endpoint). Provide credentials either as environment variables (`WATERLINK_USERNAME`, `WATERLINK_PASSWORD`, `WATERLINK_CLIENT_ID`, `WATERLINK_METER_ID`) or by copying `tests/credentials.example.json` to `tests/credentials.json` (git-ignored) and filling it in. Then run:

```bash
pytest -m live -s
```

The live tests save the raw API responses to git-ignored `tests/live_*_sample.json` files, which is useful for inspecting the undocumented response schema.
