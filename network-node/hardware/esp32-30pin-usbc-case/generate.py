"""Parametric, millimetre-scale enclosure. STL coordinates are print-ready.

Run: python generate.py [--parameters dimensions.json] [--output DIRECTORY]
Photos are dimensional estimates, not a manufacturer-controlled drawing.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

import manifold3d as m
import numpy as np
import trimesh


def box(x0, x1, y0, y1, z0, z1):
    assert x1 > x0 and y1 > y0 and z1 > z0
    return m.Manifold.cube((x1-x0, y1-y0, z1-z0)).translate((x0, y0, z0))


def rounded(w, length, height, radius, x=0, y=0, z=0):
    return (m.CrossSection.square((w-2*radius, length-2*radius), center=True)
            .offset(radius, circular_segments=48).extrude(height).translate((x, y, z)))


def cylinder(x, y, z0, height, diameter, upper=None):
    return m.Manifold.cylinder(height, diameter/2, diameter/2 if upper is None else upper/2,
                               circular_segments=32).translate((x, y, z0))


def xz_prism(points, y0, y1):
    return m.CrossSection([points]).extrude(y1-y0).rotate((90, 0, 0)).translate((0, y1, 0))


def yz_prism(points, x0, x1):
    return m.CrossSection([points]).extrude(x1-x0).transform(
        ((0, 0, 1, x0), (1, 0, 0, 0), (0, 1, 0, 0)))


def union(shapes):
    result = m.Manifold()
    for shape in shapes:
        result = result + shape
    return result


def mesh(shape):
    assert shape.status() == m.Error.NoError
    data = shape.to_mesh()
    return trimesh.Trimesh(vertices=np.asarray(data.vert_properties)[:, :3],
                           faces=np.asarray(data.tri_verts), process=True)


def build(p):
    w, length, top = p['outer_width'], p['outer_length'], p['outer_height']
    wall, floor = p['wall'], p['floor']
    iw, il = w-2*wall, length-2*wall
    pcb_w, pcb_l = p['pcb_width'], p['pcb_length']
    rail_top = p['pin_hole_bottom'] + p['pin_bay_depth']
    pcb_bottom = rail_top + p['header_height']
    pcb_top = pcb_bottom + p['pcb_thickness']
    roof_under = top-p['lid_thickness']
    skin_top = top+p['lid_raise']
    skin_bottom = top+p['lid_rim_clearance']
    assert p['lid_raise']-p['lid_rim_clearance'] >= 1.0
    assert p['free_pin_length'] < p['pin_bay_depth']
    assert roof_under-pcb_top-p['component_height'] >= 0.5
    assert iw > pcb_w+2*p['pcb_edge_clearance']
    assert il > pcb_l+2*p['pcb_end_clearance']
    assert p['pin_hole_diameter'] < p['pin_pitch']
    assert p['pin_hole_diameter'] >= 1.2
    pin_y = [-pcb_l/2+p['first_pin_from_usb_edge']+i*p['pin_pitch']
             for i in range(p['pins_per_row'])]
    assert min(pin_y) > -pcb_l/2+1.3 and max(pin_y) < pcb_l/2-1.3

    case = rounded(w, length, top, p['corner_radius'])
    case -= rounded(iw, il, top+1, max(.5, p['corner_radius']-wall), z=floor)
    # Header plastics carry the board. Pins have clearance and do not bottom out.
    rails = [box(x-2.1, x+2.1, min(pin_y)-2.07, max(pin_y)+2.07,
                 floor-.05, rail_top) for x in [-p['row_spacing']/2, p['row_spacing']/2]]
    case += union(rails)
    # Board edges stop cable insertion forces before they can bend the pins.
    guides = []
    for sign in [-1, 1]:
        x0 = pcb_w/2+p['pcb_edge_clearance']
        guide = box(x0, iw/2+.1, -2.5, 2.5, floor-.05, pcb_top-.2)
        if sign < 0:
            guide = guide.mirror((1, 0, 0))
        for y in [-pcb_l/2+3, pcb_l/2-3]:
            guides.append(guide.translate((0, y, 0)))
    for sign in [-1, 1]:
        end = box(-2, 2, pcb_l/2+p['pcb_end_clearance'], il/2+.1,
                  floor-.05, pcb_top-.2)
        if sign < 0:
            end = end.mirror((0, 1, 0))
        for x in [-11.8, 11.8]:
            guides.append(end.translate((x, 0, 0)))
    case += union(guides)
    holes = []
    for x in [-p['row_spacing']/2, p['row_spacing']/2]:
        for y in pin_y:
            holes.append(cylinder(x, y, p['pin_hole_bottom'], p['pin_bay_depth']+.1,
                                  p['pin_hole_diameter']))
            holes.append(cylinder(x, y, rail_top-.6, .7, p['pin_hole_diameter'],
                                  p['pin_entry_diameter']))
    case -= union(holes)

    # Captured 45-degree slide rails: support-free slopes and separate XY/Z gaps.
    wing_outer = iw/2 + .5
    wing_bottom = roof_under-.2
    wing_top_outer = roof_under+.6
    wing_inner = iw/2-1.4
    wing = xz_prism([(wing_inner, wing_bottom), (wing_outer, wing_bottom),
                     (wing_outer, wing_top_outer), (iw/2-.9, top),
                     (wing_inner, top)], -il/2+1.4, length/2+.4)
    clearance_x = p['slide_xy_clearance']
    clearance_z = p['slide_z_clearance']
    gx0, gx1 = iw/2-.1, wing_outer+clearance_x
    # Ceiling follows the wing's 45-degree ramp with 0.25 mm vertical clearance.
    ceiling = lambda x: wing_top_outer + wing_outer-x+clearance_z
    groove = xz_prism([(gx0, wing_bottom-clearance_z),
                       (gx1, wing_bottom-clearance_z),
                       (gx1, ceiling(gx1)), (gx0, ceiling(gx0))],
                      -il/2+.9, length/2+.5)
    case -= groove + groove.mirror((1, 0, 0))
    # Rear entry clears the flange; its lower wall is the positive latch catch.
    case -= box(-gx1-.05, gx1+.05, il/2-1.5, length/2+.5,
                wing_bottom-clearance_z-.02, top+1)
    case -= box(-p['usb_opening_width']/2, p['usb_opening_width']/2,
                -length/2-1, -il/2+.5, p['usb_opening_bottom'], top+1)
    for y in [-11, 0, 11]:
        case -= rounded(16, 1.6, floor+1, .75, y=y, z=-.2)

    inset = p['lid_contour_inset']
    front, rear = -il/2+p['lid_front_stop_gap'], length/2-inset
    lid = rounded(iw-1.0, rear-front, p['lid_thickness'],
                  1, y=(rear+front)/2, z=roof_under)
    lid += wing + wing.mirror((1, 0, 0))
    # Rear roof fills the entry, within the case's rounded exterior silhouette.
    lid += box(-gx1+.15, gx1-.15, il/2-1.3, rear+.1, roof_under, top)
    # Close the open USB crown with a thin, recessed bridge, not an open notch.
    nose_front, nose_rear = -length/2+inset, -pcb_l/2+1.2
    lid += rounded(p['usb_opening_width']-.6, nose_rear-nose_front,
                   p['lid_thickness'], .6, y=(nose_front+nose_rear)/2, z=roof_under)
    nose_under = top-p['usb_roof_thickness']
    lid -= yz_prism([(nose_front-1, roof_under-.2),
                     (nose_rear-.9, roof_under-.2),
                     (nose_rear-.9, roof_under),
                     (nose_rear-1.7, nose_under),
                     (nose_front-1, nose_under)], -7.2, 7.2)
    # The flat front shoulders stop against the existing inner front wall.
    # Nothing extends below the rear entry, so withdrawal stays unobstructed.
    half = p['latch_width']/2
    for x in [-half-.325, half+.325]:
        lid -= rounded(.65, p['latch_free_y']-14, 5, .25,
                       x=x, y=(p['latch_free_y']+14)/2, z=roof_under-1)
    lid -= rounded(p['latch_width']+1.3, .8, 5, .25,
                   y=p['latch_free_y']+.2, z=roof_under-1)
    lid -= box(-half, half, p['latch_root_y'], p['latch_free_y']+.01,
               roof_under-.1, top-p['latch_thickness'])
    lid -= rounded(4.5, 2.2, 5, 1, y=23, z=roof_under-1)
    without_tooth = lid
    tooth = yz_prism([(25.3, top-p['latch_thickness']+.1),
                      (26.6, p['latch_tooth_bottom']),
                      (27.25, p['latch_tooth_bottom']),
                      (27.25, top-p['latch_thickness']+.1)], -2.75, 2.75)
    lid += tooth
    contour = rounded(w-2*inset, length-2*inset, skin_top+2,
                      p['corner_radius']-inset, z=-1)
    lid = lid ^ contour
    without_tooth = without_tooth ^ contour
    # Raised crown covers the existing rim. The original sliding core and latch
    # stay at their proven Z positions; a 0.2 mm seam keeps the crown off the rim.
    crown = rounded(w-2*inset, length-2*inset, skin_top-skin_bottom,
                    p['corner_radius']-inset, z=skin_bottom)
    crown += rounded(iw-1.0, rear-front, skin_bottom-top+.5,
                     1, y=(rear+front)/2, z=top-.1)
    crown += rounded(p['usb_opening_width']-.6, nose_rear-nose_front,
                     skin_bottom-top+.5, .6,
                     y=(nose_front+nose_rear)/2, z=top-.1)
    # Open-backed thumb well leaves the entire elastic tongue at original height.
    well_front, well_rear = p['latch_root_y']-.5, length/2+1
    well = rounded(p['latch_width']+3.2, well_rear-well_front,
                   skin_top-top+2, 1,
                   y=(well_front+well_rear)/2, z=top-.5)
    crown -= well
    lid += crown
    without_tooth += crown
    openings = []
    for x in [-p['button_x'], p['button_x']]:
        openings.append(cylinder(x, p['button_y'], roof_under-1,
                                 skin_top-roof_under+2, p['button_hole_diameter']))
        openings.append(cylinder(x, p['button_y'], skin_top-.45, .55,
                                 p['button_hole_diameter'], p['button_hole_diameter']+1.1))
    # Restore the original seven straight, rounded ventilation slots.
    for y in [-15, -11, -7, -3, 1, 5, 9]:
        openings.append(rounded(18, 1.6, skin_top-roof_under+2, .75,
                                y=y, z=roof_under-1))
    all_openings = union(openings)
    lid -= all_openings
    without_tooth -= all_openings
    # Flat crown face down. The recessed tongue needs local slicer supports.
    lid_print = lid.rotate((180, 0, 0)).translate((0, 0, skin_top))

    coupon = rounded(w, 9, floor, .8)
    for x in [-p['row_spacing']/2, p['row_spacing']/2]:
        coupon += box(x-2.1, x+2.1, -4.5, 4.5, floor-.05, rail_top)
        for y in [-p['pin_pitch'], 0, p['pin_pitch']]:
            coupon -= cylinder(x, y, p['pin_hole_bottom'], p['pin_bay_depth']+.1,
                               p['pin_hole_diameter'])
            coupon -= cylinder(x, y, rail_top-.6, .7, p['pin_hole_diameter'],
                               p['pin_entry_diameter'])

    # Visual/clearance reference only; never exported as a printable assembly.
    pcb = box(-pcb_w/2, pcb_w/2, -pcb_l/2, pcb_l/2, pcb_bottom, pcb_top)
    headers = union([box(x-1.27, x+1.27, min(pin_y)-1.27, max(pin_y)+1.27,
                         rail_top, pcb_bottom) for x in [-p['row_spacing']/2, p['row_spacing']/2]])
    pins = union([box(x-.32, x+.32, y-.32, y+.32, rail_top-p['free_pin_length'], rail_top+.05)
                  for x in [-p['row_spacing']/2, p['row_spacing']/2] for y in pin_y])
    shield = box(-9, 9, -.75, 18, pcb_top+.1, pcb_top+p['component_height'])
    antenna = box(-9, 9, 18, 24.75, pcb_top+.1, pcb_top+.9)
    usb = box(-4.5, 4.5, -28.75, -21.25, pcb_top, pcb_top+3.2)
    buttons = union([box(x-2, x+2, p['button_y']-2, p['button_y']+2,
                         pcb_top, pcb_top+2.5) for x in [-p['button_x'], p['button_x']]])
    # Include conservative top-side solder envelopes along the header rows.
    solder = union([box(x-.8, x+.8, y-.8, y+.8, pcb_top, pcb_top+.9)
                    for x in [-p['row_spacing']/2, p['row_spacing']/2] for y in pin_y])
    reference = {'pcb': pcb, 'headers': headers, 'pins': pins, 'shield': shield,
                 'antenna': antenna, 'usb': usb, 'buttons': buttons, 'solder': solder}
    reference_solid = union(list(reference.values()))
    slide_positions = sorted(set([-.1, .2, .5, 65]+list(range(61))))
    outer_envelope = rounded(w, length, skin_top+2, p['corner_radius'], z=-1)
    rear_play = il/2-27.25
    checks = {'case_lid_intersection_mm3': (case ^ lid).volume(),
              'case_reference_intersection_mm3': (case ^ reference_solid).volume(),
              'lid_reference_intersection_mm3': (lid ^ reference_solid).volume(),
              'slide_without_elastic_tooth_max_collision_mm3': max(
                  (case ^ without_tooth.translate((0, dy, 0))).volume()
                  for dy in slide_positions),
              'sliding_lid_reference_max_collision_mm3': max(
                  (reference_solid ^ lid.translate((0, dy, 0))).volume()
                  for dy in slide_positions),
              'slide_sample_count': len(slide_positions),
              'lid_outside_case_silhouette_mm3': (lid-contour).volume(),
              'lid_outside_case_at_stop_limits_mm3': max(
                  (lid.translate((0, dy, 0))-outer_envelope).volume()
                  for dy in [-p['lid_front_stop_gap'], 0, rear_play]),
              'front_stop_clearance_mm': p['lid_front_stop_gap'],
              'front_stop_blocks_overtravel': (case ^ without_tooth.translate(
                  (0, -p['lid_front_stop_gap']-.1, 0))).volume() > 1e-4,
              'rear_latch_clearance_mm': rear_play,
              'rear_latch_blocks_withdrawal': (case ^ lid.translate(
                  (0, rear_play+.1, 0))).volume() > 1e-4,
              'usb_roof_clearance_mm': nose_under-pcb_top-3.2,
              'crown_raise_mm': p['lid_raise'],
              'crown_rim_clearance_mm': p['lid_rim_clearance'],
              'raised_material_above_flexible_tongue_mm3': (lid ^ box(
                  -half, half, 14, p['latch_free_y']-.3, top+.001, skin_top+1)).volume(),
              'pin_tip_floor_clearance_mm': rail_top-p['free_pin_length']-p['pin_hole_bottom'],
              'module_roof_clearance_mm': roof_under-pcb_top-p['component_height'],
              'latch_required_deflection_mm': wing_bottom-clearance_z-.02-p['latch_tooth_bottom'],
              'physical_fit_verified': False}
    assert checks['front_stop_blocks_overtravel']
    assert checks['rear_latch_blocks_withdrawal']
    for key, value in checks.items():
        if key.endswith('_mm3'):
            if value >= 1e-6:
                collision = case ^ lid if key == 'case_lid_intersection_mm3' else None
                if key == 'slide_without_elastic_tooth_max_collision_mm3':
                    collision = max((case ^ without_tooth.translate((0, dy, 0))
                                     for dy in slide_positions), key=lambda s: s.volume())
                details = [piece.bounding_box() for piece in collision.decompose()] if collision else []
                raise AssertionError((key, value, details))
    return {'case': case, 'lid': lid_print, 'pin-fit-test': coupon}, lid, reference, checks


def export(p, output):
    output.mkdir(parents=True, exist_ok=True)
    parts, assembled_lid, reference, checks = build(p)
    assembly_bounds = np.asarray((parts['case']+assembled_lid).bounding_box()).reshape(2, 3)
    record = {'units': 'mm', 'estimated_from_photos': True,
              'revision': 'lid-v0.3',
              'lid_print_orientation': 'raised_outer_face_down',
              'lid_local_support_region': 'recessed_latch_well',
              'parameters_sha256': hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest(),
              'assembled_size_mm': (assembly_bounds[1]-assembly_bounds[0]).round(4).tolist(),
              'checks': checks, 'parts': {}}
    for name, solid in parts.items():
        model = mesh(solid)
        assert model.is_watertight and model.is_winding_consistent and model.volume > 0, (
            name, model.is_watertight, model.is_winding_consistent, model.volume)
        assert np.all(model.nondegenerate_faces()), name
        assert len(model.split(only_watertight=False)) == 1, name
        model.apply_translation((0, 0, -model.bounds[0, 2]))
        path = output/f'{name}.stl'
        path.write_bytes(model.export(file_type='stl'))
        loaded = trimesh.load_mesh(path, process=True)
        assert loaded.is_watertight and loaded.is_winding_consistent
        assert len(loaded.split(only_watertight=False)) == 1
        assert abs(loaded.volume-model.volume)/model.volume < 1e-4
        record['parts'][name] = {'size_mm': model.extents.round(4).tolist(),
                                 'volume_mm3': round(model.volume, 3),
                                 'triangles': len(model.faces),
                                 'closed_connected_mesh': True,
                                 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    confirmed_case_hash = 'e96205394fe6171e27f1053b33a3eba5530040ab6c6e0edaefb575a86f0c04ed'
    record['fit_status'] = {
        'case_matches_user_confirmed_v01': record['parts']['case']['sha256'] == confirmed_case_hash,
        'lid_physical_fit_verified': False}
    (output/'verification.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    scene = []
    colors = {'case':'#36b8ad', 'lid':'#e9e7e0', 'pcb':'#26353f', 'headers':'#161e28',
              'pins':'#d6b77a', 'shield':'#bfc7cf', 'antenna':'#435b50', 'usb':'#afbdc9',
              'buttons':'#414b55', 'solder':'#c5cad0'}
    colors['pin-fit-test'] = '#edb96c'
    for name, solid in {'case':parts['case'], 'lid':assembled_lid,
                        'pin-fit-test':parts['pin-fit-test'], **reference}.items():
        model = mesh(solid)
        scene.append({'name': name, 'color': colors[name],
                      'v': model.vertices.round(4).tolist(), 'f':model.faces.tolist()})
    template = Path(__file__).with_name('preview-template.html').read_text(encoding='utf-8')
    (output/'preview.html').write_text(template.replace('__MESH_DATA__',
        json.dumps(scene, separators=(',',':'))), encoding='utf-8')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parameters', type=Path, default=Path(__file__).with_name('dimensions.json'))
    parser.add_argument('--output', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    export(json.loads(args.parameters.read_text(encoding='utf-8')), args.output)
