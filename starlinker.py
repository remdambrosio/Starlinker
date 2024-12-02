#
# Title: starlinker.py
# Authors: Rem D'Ambrosio
# Created: 2024-06-25
# Description: updates nicknames in Starlink API
#              finds site/router associations by checking current name and lat/lon against two internal network monitoring services
#              outputs CSV report, appropriate for visualization using PowerBI
#

import argparse
import re
import math
import csv

import sys
import os
sys.path.append(os.path.join('..', 'pythonAPIs'))

from NicknamePackage import NicknamePackage

# Internal services have been anonymized as "Nox" and "Venus"
from StarlinkAPI import StarlinkAPI
from NoxAPI import NoxAPI
from VenusAPI import VenusAPI


# ========================================================================================================================================================
# MAIN
# ========================================================================================================================================================

def main():
    parser = argparse.ArgumentParser(description='corrects nicknames via Starlink API')
    parser.add_argument('-hi', '--hidden', action='store_true', help='pull hidden current nicknames from local file')
    parser.add_argument('-pu', '--push', action='store_true', help='push recommended nickname updates to Starlink')
    parser.add_argument('-re', '--report', action='store_true', help='write report to csv file')
    parser.add_argument('-fi', '--filename', type=str, help='filename/path for report', default='nickname_updates.csv')
    args = parser.parse_args()

    filename = args.filename
    star_api = StarlinkAPI()
    nox_api = NoxAPI()
    venus_api = VenusAPI()

    print("Pulling from Starlink API to get our Starlink devices...")
    nick_updates = pull_starlinks_to_update(star_api)                                           # dict: NicknamePackage objects for all active Starlinks, to be populated
    star_locations = pull_star_locations(star_api)                                              # dict: Starlink location data
    print("Pulling from Venus API to get Starlink-connected routers...")
    venus_routers = pull_venus_routers(venus_api)                                                     # set: names of routers connected to Starlink ISP
    print("Pulling from Nox API to get info for those routers...")
    sites, router_ids, nox_locations = pull_nox_sites_routers_locations(nox_api, venus_routers)      # 3 dicts: site associations, router id/name pairings, and locations
    
    if args.hidden:
        print("Pulling hidden/GUI-only nicknames from local file...")
        nick_updates = get_hidden_nicks(nick_updates)

    print("Matching current nickname in Starlink to Nox name and Venus ISP...")                 # populate NicknamePackages with associations
    nick_updates = check_cur_nicks(nick_updates, sites)
    print("Matching lat/lon in Starlink to Nox location and Venus ISP...")
    nick_updates = check_locations(nick_updates, venus_routers, star_locations, nox_locations, router_ids)

    print("Recommending updated nicknames...")
    for update in nick_updates.values(): update.recommend_nickname()                            # add a recommendation to NicknamePackages based on associations

    if args.push:
        push_updates(star_api, nick_updates)
        print("=== Pushed updates to Starlink API ===")
    
    if args.report:
        to_csv(filename, nick_updates)
        print("=== Wrote report to " + filename + " ===")


# ========================================================================================================================================================
# CHECKERS
# ========================================================================================================================================================


def check_cur_nicks(nick_updates: dict, sites: dict):
    """
    Finds router/site based on current nickname in Starlink API
    """
    for update in nick_updates.values():
        if update.cur_nick:                                                                             # if current nickname exists
            if router_search := re.search(r'anonymized_regex', update.cur_nick):                        # if nick contains [routername], use it
                router_name = router_search.group(1).upper()
                update.cur_nick_router = router_name
            if site_search := re.search(r'anonymized_regex', update.cur_nick):                          # if nick contains [sitename], find [routername] via Nox data
                site_name = site_search.group(1).upper()
                if site_name in sites:
                    update.cur_nick_site = site_name
                    if not update.cur_nick_router:                                                      # if router name not already found, try to find from site name
                        router_names = sites[site_name]
                        if (len(router_names) < 2) and (router_at_site_search := re.search(r'anonymized_regex', router_names[0])):      # if only one router at site, with valid name
                            router_name = router_at_site_search.group(1).upper()
                            update.cur_nick_router = router_name
            elif update.cur_nick_router:
                for site_name in sites.keys():                                                          # if router name present in nick, but site name not (shouldn't happen)
                    if update.cur_nick_router in sites[site_name]:                                      # try to match router to site via Nox sites/routers dict
                        update.cur_nick_site = site_name
    return nick_updates


def check_locations(nick_updates: dict, venus_routers: set, star_locations: dict, nox_locations: dict, router_ids: dict):
    """
    Finds router/site by matching lat/lon in Starlink to Nox
    """
    update_locations = {}                                               # build dict of dicts for Starlink locations
    for update in nick_updates.values():                                # key = Starlink API internal address, val = sln/lat/lon
        adr = update.adr
        sln = update.sln
        update_locations[adr] = {'sln':sln, 'lat':None, 'lon':None}

    for adr in star_locations.keys():                                   # retrieve lat/lon corresponding to each Starlink address
        if adr in update_locations:
            update_locations[adr]['lat'] = star_locations[adr]['lat']
            update_locations[adr]['lon'] = star_locations[adr]['lon']

    matches = {}                                                        # dict to track multiple routers at same location; key = router_name, val = distance from match
    for nox_id, router in nox_locations.items():
        nox_lat = router['latitude']
        nox_lon = router['longitude']
        for adr in update_locations:                                    # check if Starlink devices are close to Nox routers
            sl_sln = update_locations[adr]['sln']
            sl_lat = update_locations[adr]['lat']
            sl_lon = update_locations[adr]['lon']
            distance = get_distance(nox_lat, nox_lon, sl_lat, sl_lon)
            if distance < 300:
                if nox_id in router_ids:
                    nox_name = router_ids[nox_id]['name']
                    nox_site = router_ids[nox_id]['site'].upper()
                    if router_search := re.search(r'anonymized_regex', nox_name):
                        router_name = router_search.group(1).upper()
                        if router_name in venus_routers:                               # that router is connected to Starlink ISP
                            if router_name in matches:                              # if a previous match was closer, skip
                                if distance > matches[router_name]:
                                    continue
                            matches[router_name] = distance
                            nick_updates[sl_sln].location_router = router_name
                            nick_updates[sl_sln].location_site = nox_site

    return nick_updates


def get_distance(lat1, lon1, lat2, lon2):
    """
    calculates distance in metres between two lat/lon pairs, using Haversine formula
    """
    earth_radius = 6371000
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    distance = earth_radius * c
    return distance


# ========================================================================================================================================================
# INPUTS
# ========================================================================================================================================================


def pull_starlinks_to_update(star_api):
    """
    Pulls from StarLink to populate a dict of NicknamePackages, with key = service line number
    """
    starlinks_to_update = {}
    page = 0                                                                        # first set of pulls: get all active Starlinks
    last = False
    while (last == False):
        lines = star_api.get_service_lines(page)
        for line in lines['content']['results']:
            if line['active'] == False:                                             # skip inactive lines
                continue

            cur_nick = line['nickname']
            name_src = 'none'
            if cur_nick:
                name_src = 'API'

                if "mobile" in cur_nick.lower():                                    # skip mobile starlinks
                    continue
                    
                if kit_search := re.search(r'anonymized_regex', cur_nick):          # initial kit number guess based on current nickname
                    kit = kit_search.group().upper()

            sln = line['serviceLineNumber']                                         # service line number
            adr = line['addressReferenceId']                                        # internal address code, for finding lat/lon later

            starlinks_to_update[sln] = NicknamePackage(cur_nick=cur_nick, sln=sln, kit=kit, adr=adr, name_src=name_src)

        last = lines['content']['isLastPage']
        page += 1

    page = 0                                                                        # second set of pulls: populate kit # based on user terminal
    last = False
    while (last == False):
        terminals = star_api.get_user_terminals(page)
        for terminal in terminals['content']['results']:
            sln = terminal['serviceLineNumber']
            if sln in starlinks_to_update:
                update = starlinks_to_update[sln]
                kit = terminal['kitSerialNumber']
                if kit:                                                             # if kit field populated in API, overwrite kit #
                    if kit_search := re.search(r'anonymized_regex', kit):
                        kit_found = kit_search.group().upper()
                        update.kit = kit_found

        last = terminals['content']['isLastPage']
        page += 1

    return starlinks_to_update


def pull_star_locations(star_api):
    """
    Pulls from StarLink to populate a dict of dicts, with key = Starlink address, value = Starlink sln/latitude/longitude
    """
    locations = {}      
    page = 0
    last = False
    while (last == False):
        lines = star_api.get_addresses(page)
        for line in lines['content']['results']:
            # anonymized interaction with API
            next
        page += 1
    return locations


def pull_venus_routers(venus_api):
    """
    Pulls from Venus to populate set of router names associated with Starlink ISP
    """
    venus_routers = set()
    venus_routers_list = venus_api.pull_routers()                     # all routers in Venus
    for router in venus_routers_list:                          
        if 'links' in router:
            for link in router['anonymized']:
                if link.get('isp') == 'Starlink':               # add only those routers with Starlink ISP link
                    # anonymized interaction with API
                    next
    return venus_routers


def pull_nox_sites_routers_locations(nox_api, venus_routers: set):
    """
    Pulls from Nox to populate three dicts:
    1) key = site code, value = list of Starlink-connected routers at that site (to determine router names from site codes)
    2) key = router ID, value = dict of router name and site (to map router IDs to router names)
    3) key = router ID, value = dict of location data (to compare with Starlink locations)
    """
    sites_with_routers = {}
    router_ids = {}

    routers = nox_api.pull_routers()                                                        # first set of pulls, populating 1) and 2)
    for id, dict in routers.items():
        router_name = dict['anonymized']
        if router_name_search := re.search(r'anonymized_regex', router_name):
            router_name_truncated = router_name_search.group(1).upper()                    # Nox names have a prefix, which we need later
            if router_name_truncated in venus_routers:                                     # omit it here for comparison to Venus
                desc = dict['anonymized']

                if id not in router_ids:
                    router_ids[id] = {}

                router_ids[id]['name'] = router_name                                       # add this router to router_ids dict

                router_ids[id]['site'] = ''
                if desc and (site_search := re.search(r'anonymized_regex', desc)):         # get site code for that router
                    site_name = site_search.group(1).upper()
                    router_ids[id]['site'] = site_name                                     # add site to router dict

                    if site_name not in sites_with_routers:                                # if new site, add to site dict
                        sites_with_routers[site_name] = []

                    sites_with_routers[site_name].append(router_name)                      # add router to site in site dict

    nox_locations = nox_api.pull_locations_dict()                                          # second pull, populating 3)

    return sites_with_routers, router_ids, nox_locations


def get_hidden_nicks(nick_updates: dict):
    """
    Populates missing current nicknames (set in GUI, but not in API) from .csv file w/ col1 = name and col2 = sln
    """
    hidden_nicks = {}
    with open('hidden_nicks.csv', mode='r') as file:
        csv_reader = csv.reader(file)
        for row in csv_reader:
            name = row[0]
            sln = row[1]
            hidden_nicks[sln] = name

    for update in nick_updates.values():
        if not update.cur_nick:
            if update.sln:
                if update.sln in hidden_nicks:
                    update.cur_nick = hidden_nicks[update.sln]
                    update.note += "GUI-only nickname retrieved from local file; "
                    update.name_src = 'GUI'

    return nick_updates


# ========================================================================================================================================================
# OUTPUTS
# ========================================================================================================================================================


def push_updates(star_api, nick_updates: dict):
    """
    Pushes recommended nickname updates to Starlink API
    """
    for update in nick_updates.values():
        if update.rec_nick:
            if update.router_src == 'current nickname':                         # for now, trusting only current-nickname-based recs
                if update.rec_nick != update.cur_nick:
                    if star_api.update_nickname(update.sln, update.rec_nick):                               
                        update.updated = True
                        continue
        if update.cur_nick and update.name_src == 'GUI':                        # also push GUI nicks to API, even if they may not be correct
            if update.rec_nick != update.cur_nick:
                    if star_api.update_nickname(update.sln, update.cur_nick):                               
                        update.updated = True
    return


def to_csv(filename: str, nick_updates: dict):
    """
    Writes recommended nicknames to .csv file
    """
    updates_head = [['Current Nickname',                                        # column headers for csv
                     'Starlink SLN',
                     'Starlink Kit #',
                     'Starlink Address',

                     'Router via Nick',
                     'Site via Nick',

                     'Router via Lat/Lon',
                     'Site via Lat/Lon',

                     'Recommended Nickname',
                     'Note',
                     'Starlink API Updated',

                     'Current Name Source',
                     'Router Source',
                     'Result'
                     ]]

    updates_list = []
    for update in nick_updates.values():                                        # content for csv
        line = update.to_list()
        updates_list.append(line)

    updates_list = updates_head + updates_list
    
    with open(filename, 'w') as file:
        writer = csv.writer(file)
        for row in updates_list:
            writer.writerow(row)
    
    return


if __name__ == '__main__':
    main()
