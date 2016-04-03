import argparse, csv, locale, os, re
import xml.etree.ElementTree as etree
from datetime import datetime
from getpass import getpass # for the continue/abort prompt
from os import path

player_log_patterns = ['^((?:[^-]|-[^ ])+) -.*World request received: (.*)$', '^((?:[^-]|-[^ ])+) -.User left (.*)$']

namespaces = { 'xsi': 'http://www.w3.org/2001/XMLSchema-instance' }

type_attrib = '{http://www.w3.org/2001/XMLSchema-instance}type'

part_types = ['MyObjectBuilder_Wheel', 'MyObjectBuilder_PistonTop', 'MyObjectBuilder_MotorRotor', 'MyObjectBuilder_MotorAdvancedRotor']

respawn_ship_names = ['Atmospheric Lander mk.1', 'RespawnShip', 'RespawnShip2']

entity_xpath_template = './SectorObjects/MyObjectBuilder_EntityBase[@xsi:type="%s"]'
cubegrid_xpath = entity_xpath_template % 'MyObjectBuilder_CubeGrid'

cubeblock_xpath = './CubeBlocks/MyObjectBuilder_CubeBlock'
cubeblock_xpath_template = cubeblock_xpath + '[@xsi:type="%s"]'
battery_xpath = cubeblock_xpath_template % 'MyObjectBuilder_BatteryBlock'
reactor_xpath = cubeblock_xpath_template % 'MyObjectBuilder_Reactor'
projector_xpath = cubeblock_xpath_template % 'MyObjectBuilder_Projector'
timer_xpath = cubeblock_xpath_template % 'MyObjectBuilder_TimerBlock'
enabled_timer_xpath = timer_xpath + "[Enabled='true']"

cubegrid_start_xml = '<MyObjectBuilder_EntityBase xsi:type="MyObjectBuilder_CubeGrid">'
cubegrid_end_xml = '</MyObjectBuilder_EntityBase>'
entity_id_xml = '<EntityId>%d</EntityId>'

class CubeGrid(object):
    def __init__(self, id, name, owner_ids, owner_names, block_count, battery_count, stored_power, reactor_count, reactor_uranium_amount, projector_count, projected_blocks, timer_count, enabled_timer_count, part_of_something, block_types, deletion_reasons=[]):
        self.id = id
        self.name = name
        self.owner_ids = owner_ids
        self.owner_names = owner_names
        self.block_count = block_count
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
        batteries = entity.findall(battery_xpath, namespaces)
        reactors = entity.findall(reactor_xpath, namespaces)
        projectors = entity.findall(projector_xpath, namespaces)
        timers = entity.findall(timer_xpath, namespaces)
        enabled_timers = entity.findall(enabled_timer_xpath, namespaces)

        block_types = get_block_types(all_blocks)
        used_part_types = [block_type for block_type in block_types if block_type in part_types]

        owner_ids = get_owner_ids(all_blocks)
        owner_names = [player_id_to_name[owner_id] for owner_id in owner_ids]

        stored_power = get_stored_power(batteries)
        reactor_uranium_amount = get_inventory_amount(reactors)

        projected_block_count = get_projected_block_count(projectors)

        cubegrids.append(CubeGrid(\
            id, name, owner_ids, owner_names, len(all_blocks), \
            len(batteries), stored_power, len(reactors), reactor_uranium_amount, \
            len(projectors), projected_block_count, \
            len(timers), len(enabled_timers), \
            len(used_part_types) > 0, block_types))

    return cubegrids

def get_cubegrids_to_delete(cubegrids, delete_trash, delete_respawn_ships, delete_player_names):
    to_delete = set()

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

    if delete_respawn_ships:
        for cubegrid in cubegrids:
            if cubegrid.name in respawn_ship_names:
                cubegrid.deletion_reasons.append("Respawn Ship")
                to_delete.add(cubegrid)

    for cubegrid in cubegrids:
        if len(cubegrid.owner_names) == 0:
            continue

        if all([owner_name in delete_player_names for owner_name in cubegrid.owner_names]):
            cubegrid.deletion_reasons.append("Inactive Owners")
            to_delete.add(cubegrid)

    return to_delete

def delete_cubegrids(file_in, file_out, cubegrids_to_delete):
    # not parsing the file as XML to preserve whitespace, encoding and namespaces,
    # so that the file can be easily diff'ed and because SE might not load it otherwise

    ids_to_delete =  [cubegrid.id for cubegrid in cubegrids_to_delete]
    entity_id_xmls_to_delete = [entity_id_xml % id for id in ids_to_delete]

    with open(file_in, 'rb') as f:
        content = f.read()

    next_pos = 0

    while True:
        grid_start_pos = content.find(cubegrid_start_xml, next_pos)
        if grid_start_pos == -1:
            break # no more cubegrids?

        while content[grid_start_pos - 1] in [' ', '\t']:
            grid_start_pos -= 1

        grid_end_pos = content.find(cubegrid_end_xml, grid_start_pos)
        if grid_end_pos == -1:
            break # invalid XML?

        next_pos = grid_end_pos + len(cubegrid_end_xml)

        while content[next_pos] in ['\r', '\n']:
            next_pos += 1

        delete = False

        for xml in entity_id_xmls_to_delete:
            if content.find(xml, grid_start_pos, next_pos) != -1:
                delete = True
                break

        if not delete:
            continue

        content = content[:grid_start_pos] + content[next_pos:]
        next_pos = grid_start_pos

    with open(file_out, 'wb') as f:
        f.write(content)

def get_player_seen_dict(log_dir):
    log_files = sorted([log_dir + '/' + file for file in os.listdir(log_dir) if path.splitext(file)[1] == '.log'])

    log_file_index = 0
    player_seen = dict()

    for log_file in log_files:
        print "Parsing log file %d out of %d" % (log_file_index, len(log_files))
        
        with open(log_file) as f:
            for line in f.readlines():
                for pattern in player_log_patterns:
                    match = re.match(pattern, line)

                    if match is None:
                        continue

                    date_str = match.group(1)
                    player = match.group(2)

                    player_seen[player] = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S.%f')

        log_file_index += 1

    return player_seen

def get_player_names_for_deletion(player_seen, delete_after_days, keep_players=[]):
    delete_player_names = set()

    for (name, last_seen) in player_seen.items():
        if name in keep_players:
            continue

        timedelta = datetime.now() - last_seen
        
        if timedelta.days > delete_after_days:
            delete_player_names.add(name)

    return delete_player_names

def get_argument_parser():
    parser = argparse.ArgumentParser(description="Space Engineers save file cleaner.")

    parser.add_argument('--csv-directory', type=str, default='.', help="the directory to place .csv files in")
    parser.add_argument('--delete-after-days', type=int, default=30, help="after how many days to delete all grids belonging to the player (0 to never delete)")
    parser.add_argument('--delete-trash', action='store_true', help="whether to delete small grids with no ownable blocks")
    parser.add_argument('--delete-respawn-ships', action='store_true', help="whether to delete respawn ships")
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
        delete_player_names = get_player_names_for_deletion(player_seen, args.delete_after_days, args.keep_player_names)
    else:
        delete_player_names = []

    print "Parsing the .sbc file..."
    sbc_tree = etree.parse(args.sbc_in)
    print "Parsing the .sbs file... This might take a while."
    sbs_tree = etree.parse(args.sbs_in)
    print "Done parsing."

    cubegrids = get_cubegrids(sbc_tree, sbs_tree)
    cubegrids_to_delete = get_cubegrids_to_delete(cubegrids, args.delete_trash, args.delete_respawn_ships, delete_player_names)

    write_player_seen_csv(player_seen, args.csv_directory + '/players.csv')
    write_cubegrid_csv(cubegrids, args.csv_directory + '/grids.csv')
    write_cubegrid_csv(cubegrids_to_delete, args.csv_directory + '/grids-delete.csv')

    print "Please review the .csv files. Then press Enter to clean-up or Ctrl-C to abort."
    getpass('')

    print "Writing the cleaned-up .sbs file..."
    delete_cubegrids(args.sbs_in, args.sbs_out, cubegrids_to_delete)
    print "Done writing."

def get_delimiter():
    locale.setlocale(locale.LC_ALL, "")
    return ';' if locale.localeconv()['decimal_point'] == ',' else '.'

def write_player_seen_csv(player_seen, filename):
    with open(filename, 'wb') as csvfile:
        writer = csv.writer(csvfile, delimiter=get_delimiter())

        writer.writerow(['Name', 'Last Seen'])

        for (name, last_seen) in player_seen.iteritems():
            writer.writerow([name, last_seen])

def write_cubegrid_csv(cubegrids, filename):
    with open(filename, 'wb') as csvfile:
        writer = csv.writer(csvfile, delimiter=get_delimiter())
        
        writer.writerow(['Name', 'Owners', 'Blocks', 'Batteries', 'Stored Power', 'Reactors', 'Reactor Uranium Amount', 'Projectors', 'Projected Blocks', 'Timers', 'Enabled Timers', 'Block Types', 'Deletion Reasons'])

        for grid in cubegrids:
            writer.writerow([
                grid.name.encode('ascii', 'replace'),
                ', '.join([name.encode('ascii', 'replace') for name in grid.owner_names]),
                grid.block_count,
                grid.battery_count,
                locale.format("%g", grid.stored_power),
                grid.reactor_count,
                locale.format("%g", grid.reactor_uranium_amount),
                grid.projector_count,
                grid.projected_blocks,
                grid.timer_count,
                grid.enabled_timer_count,
                grid.block_types,
                ', '.join(grid.deletion_reasons)])

if __name__ == '__main__':
    run()
