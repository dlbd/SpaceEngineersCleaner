import argparse, codecs, csv, locale, os, re
import xml.etree.ElementTree as etree
from datetime import datetime
from getpass import getpass # for the continue/abort prompt
from os import path

player_log_patterns = ['^((?:[^-]|-[^ ])+) -.*World request received: ([^\r]*)(?:\r?)$', '^((?:[^-]|-[^ ])+) -.User left ([^\r]*)(?:\r?)$'] # $ matches only the \n part of the \r\n in Unicode strings

namespaces = { 'xsi': 'http://www.w3.org/2001/XMLSchema-instance' }

type_attrib = '{http://www.w3.org/2001/XMLSchema-instance}type'

part_types = ['MyObjectBuilder_Wheel', 'MyObjectBuilder_PistonTop', 'MyObjectBuilder_MotorRotor', 'MyObjectBuilder_MotorAdvancedRotor']

types_to_disable = ['MyObjectBuilder_Drill', 'MyObjectBuilder_OreDetector', 'MyObjectBuilder_Projector', 'MyObjectBuilder_TimerBlock', 'MyObjectBuilder_ShipGrinder', 'MyObjectBuilder_ShipWelder']

respawn_ship_names = ['Atmospheric Lander mk.1', 'RespawnShip', 'RespawnShip2']
default_grid_name_patterns = ['^Atmospheric Lander mk.1$', '^RespawnShip$', '^RespawnShip2$', '^Small Grid [0-9]+$', '^Small Ship [0-9]+$', '^Large Grid [0-9]+$', '^Large Ship [0-9]+$', '^Static Grid [0-9]+$', '^Platform [0-9]+$']

default_beacon_names = ['Atmospheric_Lander_mk.1']

entity_xpath_template = './SectorObjects/MyObjectBuilder_EntityBase[@xsi:type="%s"]'
cubegrid_xpath = entity_xpath_template % 'MyObjectBuilder_CubeGrid'

cubeblock_xpath = './CubeBlocks/MyObjectBuilder_CubeBlock'
cubeblock_xpath_template = cubeblock_xpath + '[@xsi:type="%s"]'
beacon_xpath = cubeblock_xpath_template % 'MyObjectBuilder_Beacon'
custom_beacon_name_xpath = beacon_xpath + '/CustomName'
battery_xpath = cubeblock_xpath_template % 'MyObjectBuilder_BatteryBlock'
reactor_xpath = cubeblock_xpath_template % 'MyObjectBuilder_Reactor'
projector_xpath = cubeblock_xpath_template % 'MyObjectBuilder_Projector'
timer_xpath = cubeblock_xpath_template % 'MyObjectBuilder_TimerBlock'
enabled_timer_xpath = timer_xpath + "[Enabled='true']"

cubegrid_start_xml = '<MyObjectBuilder_EntityBase xsi:type="MyObjectBuilder_CubeGrid">'
cubegrid_end_xml = '</MyObjectBuilder_EntityBase>'
entity_id_xml = '<EntityId>%d</EntityId>'

block_start_xml = '<MyObjectBuilder_CubeBlock '
block_end_xml = '</MyObjectBuilder_CubeBlock>'
block_type_xml = 'xsi:type="%s"'
enabled_xml = '\n          <Enabled>true</Enabled>'
disabled_xml = '\n          <Enabled>false</Enabled>'

class CubeGrid(object):
    def __init__(self, id, name, owner_ids, owner_names, block_count, beacon_count, custom_beacon_names, battery_count, stored_power, reactor_count, reactor_uranium_amount, projector_count, projected_blocks, timer_count, enabled_timer_count, part_of_something, block_types, deletion_reasons=[]):
        self.id = id
        self.name = name
        self.owner_ids = owner_ids
        self.owner_names = owner_names
        self.block_count = block_count
        self.beacon_count = beacon_count
        self.custom_beacon_names = custom_beacon_names
        self.battery_count = battery_count
        self.stored_power = stored_power
        self.reactor_count = reactor_count
        self.reactor_uranium_amount = reactor_uranium_amount
        self.projector_count = projector_count
        self.projected_blocks = projected_blocks
        self.timer_count = timer_count
        self.enabled_timer_count = enabled_timer_count
        self.part_of_something = part_of_something
        self.block_types = block_types
        self.deletion_reasons = list(deletion_reasons)

def get_player_name_dict(root):
    id_to_name = {}

    mappings = root.findall('.//*[IdentityId][DisplayName]')
    for mapping in mappings:
        id = int(mapping.findtext('IdentityId'))
        name = mapping.findtext('DisplayName')
        
        id_to_name[id] = name

    return id_to_name

def get_stored_power(batteries):
    stored_power = 0

    for battery in batteries:
        stored_power += float(battery.findtext('./CurrentStoredPower'))

    return stored_power

def get_inventory_amount(blocks):
    amount = 0

    for block in blocks:
        items = block.findall('./Inventory/Items/MyObjectBuilder_InventoryItem', namespaces)

        for item in items:
            amount += float(item.findtext('./Amount'))

    return amount

def get_projected_block_count(blocks):
    count = 0

    for block in blocks:
        projected_blocks = block.findall('./ProjectedGrid/CubeBlocks/MyObjectBuilder_CubeBlock')
        count += len(projected_blocks)

    return count

def get_owner_ids(blocks):
    owner_ids = []
    
    for block in blocks:
        for id_tag in block.findall('./Owner'):
            id = int(id_tag.text)

            if not id in owner_ids:
                owner_ids.append(id)

    return owner_ids

def get_block_types(blocks):
    types = list(set([block.get(type_attrib) for block in blocks]))
    types.sort()
    return types

def get_cubegrids(sbc_tree, sbs_tree):
    player_id_to_name = get_player_name_dict(sbc_tree.getroot())

    sbs_root = sbs_tree.getroot()
    cubegrid_entities = sbs_root.findall(cubegrid_xpath, namespaces)

    cubegrids = []

    for entity in cubegrid_entities:
        id = int(entity.findtext('./EntityId'))
        name = entity.findtext('./DisplayName')

        all_blocks = entity.findall(cubeblock_xpath, namespaces)
        beacons = entity.findall(beacon_xpath, namespaces)
        batteries = entity.findall(battery_xpath, namespaces)
        reactors = entity.findall(reactor_xpath, namespaces)
        projectors = entity.findall(projector_xpath, namespaces)
        timers = entity.findall(timer_xpath, namespaces)
        enabled_timers = entity.findall(enabled_timer_xpath, namespaces)

        custom_beacon_name_entities = entity.findall(custom_beacon_name_xpath, namespaces)
        custom_beacon_names = [name_entity.text for name_entity in custom_beacon_name_entities]

        block_types = get_block_types(all_blocks)
        used_part_types = [block_type for block_type in block_types if block_type in part_types]

        owner_ids = get_owner_ids(all_blocks)
        owner_names = [player_id_to_name[owner_id] for owner_id in owner_ids]

        stored_power = get_stored_power(batteries)
        reactor_uranium_amount = get_inventory_amount(reactors)

        projected_block_count = get_projected_block_count(projectors)

        cubegrids.append(CubeGrid(\
            id, name, owner_ids, owner_names, len(all_blocks), \
            len(beacons), custom_beacon_names, \
            len(batteries), stored_power, len(reactors), reactor_uranium_amount, \
            len(projectors), projected_block_count, \
            len(timers), len(enabled_timers), \
            len(used_part_types) > 0, block_types))

    return cubegrids

def get_cubegrids_to_delete(cubegrids, delete_trash, delete_respawn_ships, delete_default_names, are_all_players_deletable, are_all_players_inactive):
    to_delete = set()

    # delete trash
    if delete_trash:
        for cubegrid in cubegrids:
            # skip grids that are probably a part of something (wheels, rotors, pistons)
            if cubegrid.part_of_something:
                continue

            # skip grids that have an owner
            if len(cubegrid.owner_ids) > 0:
                continue

            # skip large grids
            if cubegrid.block_count > 50:
                continue;

            cubegrid.deletion_reasons.append("Trash")
            to_delete.add(cubegrid)

    # delete ships with default names, except those with beacons
    if delete_default_names:
        for cubegrid in cubegrids:
            if cubegrid.part_of_something:
                continue

            if all((re.match(pattern, cubegrid.name) is None for pattern in default_grid_name_patterns)):
                continue

            if not are_all_players_deletable(cubegrid.owner_names):
                continue

            grids_default_beacon_names = [beacon_name for beacon_name in cubegrid.custom_beacon_names if beacon_name in default_beacon_names]
            if cubegrid.beacon_count > 0 or cubegrid.beacon_count != len(grids_default_beacon_names):
                continue

            cubegrid.deletion_reasons.append("Default Name & No Custom Beacon")
            to_delete.add(cubegrid)

    # delete respawn ships
    if delete_respawn_ships:
        for cubegrid in cubegrids:
            if cubegrid.name in respawn_ship_names:
                cubegrid.deletion_reasons.append("Respawn Ship")
                to_delete.add(cubegrid)

    # delete grids of inactive owners, of owners with no med rooms and of owners having only a respawn ship
    for cubegrid in cubegrids:
        if len(cubegrid.owner_names) == 0:
            continue

        if not are_all_players_deletable(cubegrid.owner_names):
            continue

        if are_all_players_inactive(cubegrid.owner_names):
            cubegrid.deletion_reasons.append("Inactive Owners")
            to_delete.add(cubegrid)

        if all_players_have_no_powered_medrooms(cubegrids, cubegrid.owner_names):
            cubegrid.deletion_reasons.append("Dead-ish Owners")
            to_delete.add(cubegrid)

        if all_players_have_only_respawn_ships(cubegrids, cubegrid.owner_names):
            cubegrid.deletion_reasons.append("Respawn-Ship Only Owners")
            to_delete.add(cubegrid)

    return to_delete

def make_replacements(content, start_substr, end_substr, content_matcher, content_changer, include_surrounding_whitespace=True):
    next_pos = 0

    while True:
        start_pos = content.find(start_substr, next_pos)
        if start_pos == -1:
            break # no more matching substrings

        while include_surrounding_whitespace and content[start_pos - 1] in [' ', '\t']:
            start_pos -= 1

        next_pos = content.find(end_substr, start_pos)
        if next_pos == -1:
            break # invalid XML?

        next_pos = next_pos + len(end_substr)

        while include_surrounding_whitespace and content[next_pos] in ['\r', '\n']:
            next_pos += 1

        matched = content_matcher(content, start_pos, next_pos)

        if not matched:
            continue

        content = content_changer(content, start_pos, next_pos)
        next_pos = start_pos

    return content

def clean_up(file_in, file_out, cubegrids_to_delete, disable_nonessential_blocks=True):
    # not parsing the file as XML to preserve whitespace, encoding and namespaces,
    # so that the file can be easily diff'ed and because SE might not load it otherwise

    with open(file_in, 'rb') as f:
        content = f.read()

    next_pos = 0

    # delete specified grids

    ids_to_delete =  [cubegrid.id for cubegrid in cubegrids_to_delete]
    entity_id_xmls_to_delete = [entity_id_xml % id for id in ids_to_delete]

    content = make_replacements(content, cubegrid_start_xml, cubegrid_end_xml, \
       lambda text, start_pos, next_pos: any((text.find(xml, start_pos, next_pos) != -1 for xml in entity_id_xmls_to_delete)), \
       lambda text, start_pos, next_pos: text[:start_pos] + text[next_pos:])

    # disable certain blocks
    
    type_xmls_to_disable = [block_type_xml % type for type in types_to_disable]

    content = make_replacements(content, block_start_xml, block_end_xml, \
       lambda text, start_pos, next_pos: text.find(enabled_xml, start_pos, next_pos) != -1 and any((text.find(xml, start_pos, next_pos) != -1 for xml in type_xmls_to_disable)), \
       lambda text, start_pos, next_pos: text[:start_pos] + text[start_pos:next_pos].replace(enabled_xml, disabled_xml, 1) + text[next_pos:])

    with open(file_out, 'wb') as f:
        f.write(content)

def get_player_seen_dict(log_dir):
    log_files = sorted([log_dir + '/' + file for file in os.listdir(log_dir) if path.splitext(file)[1] == '.log'])

    log_file_index = 0
    player_seen = dict()

    for log_file in log_files:
        log_file_index += 1
        print "Parsing log file %d out of %d" % (log_file_index, len(log_files))
        
        with codecs.open(log_file, encoding='utf-8') as f:
            for line in f.readlines():
                for pattern in player_log_patterns:
                    match = re.match(pattern, line)

                    if match is None:
                        continue

                    date_str = match.group(1)
                    player = match.group(2)

                    player_seen[player] = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S.%f')

    return player_seen

def player_has_a_powered_medroom(cubegrids, name):
    for cubegrid in cubegrids:
        if cubegrid.stored_power == 0 and cubegrid.reactor_uranium_amount == 0:
            continue

        if not 'MyObjectBuilder_MedicalRoom' in cubegrid.block_types:
            continue

        if not name in cubegrid.owner_names:
            continue

        return True

    return False

def player_has_only_respawn_ship(cubegrids, name):
    return all((name not in cubegrid.owner_names or cubegrid.name in respawn_ship_names for cubegrid in cubegrids))

def all_players_have_no_powered_medrooms(cubegrids, names):
    return all((not player_has_a_powered_medroom(cubegrids, name) for name in names))

def all_players_have_only_respawn_ships(cubegrids, names):
    return all((player_has_only_respawn_ship(cubegrids, name) for name in names))

def get_argument_parser():
    parser = argparse.ArgumentParser(description="Space Engineers save file cleaner.")

    parser.add_argument('--csv-directory', type=str, default='.', help="the directory to place .csv files in")
    parser.add_argument('--delete-after-days', type=int, default=30, help="after how many days to delete all grids belonging to the player (0 to never delete)")
    parser.add_argument('--delete-trash', action='store_true', help="whether to delete small grids with no ownable blocks")
    parser.add_argument('--delete-respawn-ships', action='store_true', help="whether to delete respawn ships")
    parser.add_argument('--delete-default-names', action='store_true', help="whether to delete the grids with default names")
    parser.add_argument('--keep-player-names', nargs='*', type=str, default=[], help="player names whose grids are always kept")
    parser.add_argument('--log-directory', type=str, default='logs/', help=r"the directory containing the .log files (typically, %%APPDATA%%/SpaceEngineersDedicated)")
    parser.add_argument('--sbc-in', type=str, default='Sandbox.sbc', help="the Sandbox.sbc file to be read")
    parser.add_argument('--sbs-in', type=str, default='SANDBOX_0_0_0_.sbs', help="the SANDBOX_0_0_0_.sbs to be read")
    parser.add_argument('--sbs-out', type=str, default='SANDBOX_0_0_0_.cleanedup.sbs', help="the SANDBOX_0_0_0_.sbs to be written")

    return parser

def run():
    arg_parser = get_argument_parser()
    args = arg_parser.parse_args()

    if args.delete_after_days != 0:
        print "Parsing the logs..."
        
        player_seen = get_player_seen_dict(args.log_directory)
        write_player_seen_csv(player_seen, args.csv_directory + '/players.csv')

        is_player_active = lambda name: name in player_seen and (datetime.now() - player_seen[name]).days <= args.delete_after_days
    else:
        is_player_active = lambda name: True

    are_all_players_inactive = lambda player_names: all([not is_player_active(player_name) for player_name in player_names])
    are_all_players_deletable = lambda player_names: not any([player_name in args.keep_player_names for player_name in player_names])

    print "Parsing the .sbc file..."
    sbc_tree = etree.parse(args.sbc_in)
    print "Parsing the .sbs file... This might take a while."
    sbs_tree = etree.parse(args.sbs_in)
    print "Done parsing."

    cubegrids = get_cubegrids(sbc_tree, sbs_tree)
    cubegrids_to_delete = get_cubegrids_to_delete(cubegrids, args.delete_trash, args.delete_respawn_ships, args.delete_default_names, are_all_players_deletable, are_all_players_inactive)

    write_cubegrid_csv(cubegrids, args.csv_directory + '/grids.csv')
    write_cubegrid_csv(cubegrids_to_delete, args.csv_directory + '/grids-delete.csv')

    if len(cubegrids_to_delete) == 0:
        print "There is nothing to delete."
        return

    print "Please review the .csv files. Then press Enter to clean-up or Ctrl-C to abort."
    getpass('')

    print "Writing the cleaned-up .sbs file..."
    clean_up(args.sbs_in, args.sbs_out, cubegrids_to_delete)
    print "Done writing."

def get_delimiter():
    locale.setlocale(locale.LC_ALL, "")
    return ';' if locale.localeconv()['decimal_point'] == ',' else '.'

def write_player_seen_csv(player_seen, filename):
    with open(filename, 'wb') as csvfile:
        writer = csv.writer(csvfile, delimiter=get_delimiter())

        writer.writerow(['Name', 'Last Seen'])

        for (name, last_seen) in player_seen.iteritems():
            writer.writerow([name.encode('utf-8'), last_seen])

def write_cubegrid_csv(cubegrids, filename):
    with open(filename, 'wb') as csvfile:
        writer = csv.writer(csvfile, delimiter=get_delimiter())
        
        writer.writerow(['Name', 'Owners', 'Blocks', 'Beacons', 'Custom Beacon Names', 'Batteries', 'Stored Power', 'Reactors', 'Reactor Uranium Amount', 'Projectors', 'Projected Blocks', 'Timers', 'Enabled Timers', 'Block Types', 'Deletion Reasons'])

        for grid in cubegrids:
            writer.writerow([
                grid.name.encode('utf-8'),
                ', '.join([name.encode('utf-8') for name in grid.owner_names]),
                grid.block_count,
                grid.beacon_count,
                ', '.join([name.encode('utf-8') for name in grid.custom_beacon_names]),
                grid.battery_count,
                locale.format("%g", grid.stored_power),
                grid.reactor_count,
                locale.format("%g", grid.reactor_uranium_amount),
                grid.projector_count,
                grid.projected_blocks,
                grid.timer_count,
                grid.enabled_timer_count,
                ', '.join([block_type.replace('MyObjectBuilder_', '') for block_type in grid.block_types]),
                ', '.join(grid.deletion_reasons)])

if __name__ == '__main__':
    run()
