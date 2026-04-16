bl_info = {
    "name": "Solo Mode",
    "author": "Vincent Ilagan",
    "version": (1, 0, 8),
    "blender": (4, 2, 0),
    "location": "View3D > N-Panel > Solo | View3D Header",
    "description": "Isolate selected objects in the viewport. Supports multi-select, collections, and instance-aware grouping.",
    "category": "3D View",
}

import bpy


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def is_solo_active(scene):
    return scene.get("_solo_active", False)


def get_hidden_list(scene):
    raw = scene.get("_solo_hidden", "")
    if not raw:
        return []
    return [n for n in raw.split("||") if n]


def set_solo_state(scene, active, hidden_names=None):
    scene["_solo_active"] = active
    scene["_solo_hidden"] = "||".join(hidden_names or [])


# ---------------------------------------------------------------------------
# Group / hierarchy helpers
# ---------------------------------------------------------------------------

def get_root_parent(obj):
    """Return the top-most parent of an object."""
    root = obj
    while root.parent is not None:
        root = root.parent
    return root


def get_root_family(obj):
    """
    Return the object's top parent plus all its children_recursive.
    Main logic for Collection Instance Members:
    if you click any part of a grouped asset, keep the whole asset visible.
    """
    root = get_root_parent(obj)
    result = {root}
    for child in root.children_recursive:
        result.add(child)
    return result


def get_collection_instance_members_from_empty(obj):
    """
    Fallback:
    if the selected object itself is a Collection Instance Empty,
    include the objects inside that instanced collection.
    """
    result = set()

    if obj.instance_type == 'COLLECTION' and obj.instance_collection:
        for member in obj.instance_collection.objects:
            result.add(member)

    return result


def collect_solo_objects(
    scene,
    selected_objects,
    include_collections,
    include_instance_members,
):
    """
    Build the set of objects that should remain visible.
    """
    result = set(selected_objects)

    # ---------------------------------------------------------
    # Collection
    # Normal Blender collection-wide inclusion
    # ---------------------------------------------------------
    if include_collections:
        for obj in list(selected_objects):
            for col in obj.users_collection:
                for member in col.objects:
                    result.add(member)

    # ---------------------------------------------------------
    # Collection Instance Members
    # Artist logic:
    # if you select any part of a grouped / instanced object,
    # keep that whole object family visible only.
    # ---------------------------------------------------------
    if include_instance_members:
        for obj in list(selected_objects):
            # Main behavior: use root hierarchy family
            for member in get_root_family(obj):
                result.add(member)

            # Fallback for actual collection instance empty
            for member in get_collection_instance_members_from_empty(obj):
                result.add(member)

    return result


# ---------------------------------------------------------------------------
# Enter / Exit
# ---------------------------------------------------------------------------

def enter_solo(context):
    scene = context.scene
    props = scene.solo_mode_props

    include_collections = bool(props.include_collections)
    include_instance_members = bool(props.include_instance_collections)
    selected = list(context.selected_objects)

    if not selected:
        return False

    solo_set = collect_solo_objects(
        scene,
        selected,
        include_collections,
        include_instance_members,
    )

    hidden = []

    for obj in scene.objects:
        if obj not in solo_set:
            if not obj.hide_viewport:
                obj.hide_viewport = True
                hidden.append(obj.name)

    set_solo_state(scene, True, hidden)
    return True


def exit_solo(context):
    scene = context.scene

    for name in get_hidden_list(scene):
        obj = scene.objects.get(name)
        if obj is not None:
            obj.hide_viewport = False

    set_solo_state(scene, False, [])


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class SoloModeProperties(bpy.types.PropertyGroup):
    include_collections: bpy.props.BoolProperty(
        name="Collection",
        description="Also show all objects that share a collection with selected objects",
        default=False,
    )

    include_instance_collections: bpy.props.BoolProperty(
        name="Collection Instance Members",
        description=(
            "Keep the full grouped / root family of the selected object visible. "
            "Useful for cars, characters, and complex assemblies."
        ),
        default=False,
    )


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------

class OBJECT_OT_solo_mode_toggle(bpy.types.Operator):
    bl_idname = "object.solo_mode_toggle"
    bl_label = "Solo Mode"
    bl_description = "Toggle Solo Mode — isolate selected objects in the viewport (F1)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene

        if is_solo_active(scene):
            exit_solo(context)
            self.report({'INFO'}, "Solo Mode OFF — viewport restored")
        else:
            if not context.selected_objects:
                self.report({'WARNING'}, "Select at least one object first!")
                return {'CANCELLED'}

            props = scene.solo_mode_props
            info_parts = [f"{len(context.selected_objects)} object(s) isolated"]

            if props.include_collections:
                info_parts.append("+ collections")
            if props.include_instance_collections:
                info_parts.append("+ instance members")

            ok = enter_solo(context)
            if not ok:
                self.report({'WARNING'}, "Nothing selected")
                return {'CANCELLED'}

            self.report({'INFO'}, "Solo Mode ON — " + ", ".join(info_parts))

        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

        return {'FINISHED'}


# ---------------------------------------------------------------------------
# F1 Keymap
# ---------------------------------------------------------------------------

addon_keymaps = []


def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon

    if not kc:
        return

    try:
        existing_km = wm.keyconfigs.active.keymaps.get('3D View')
        if existing_km:
            for kmi in existing_km.keymap_items:
                if kmi.type == 'F1' and kmi.value == 'PRESS':
                    print(f"[Solo Mode] F1 already bound to '{kmi.idname}' — skipping.")
                    return
    except Exception:
        pass

    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(
        'object.solo_mode_toggle',
        type='F1',
        value='PRESS',
    )
    addon_keymaps.append((km, kmi))
    print("[Solo Mode] F1 shortcut registered.")


def unregister_keymap():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


# ---------------------------------------------------------------------------
# Header button
# ---------------------------------------------------------------------------

def draw_solo_header(self, context):
    layout = self.layout
    scene = context.scene
    active = is_solo_active(scene)

    row = layout.row(align=True)
    row.operator(
        "object.solo_mode_toggle",
        text="Solo",
        icon='HIDE_OFF' if active else 'HIDE_ON',
        depress=active,
    )


# ---------------------------------------------------------------------------
# N-Panel
# ---------------------------------------------------------------------------

class VIEW3D_PT_solo_mode_panel(bpy.types.Panel):
    bl_label = "Solo Mode"
    bl_idname = "VIEW3D_PT_solo_mode_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Solo"

    def draw_header(self, context):
        active = is_solo_active(context.scene)
        self.layout.label(
            text="",
            icon='HIDE_OFF' if active else 'HIDE_ON',
        )

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.solo_mode_props
        active = is_solo_active(scene)

        status_row = layout.row()
        status_row.alert = active
        status_row.label(
            text="● SOLO ACTIVE" if active else "○ Solo Off",
            icon='RADIOBUT_ON' if active else 'RADIOBUT_OFF',
        )

        layout.separator()

        op_row = layout.row()
        op_row.scale_y = 1.5
        op_row.operator(
            "object.solo_mode_toggle",
            text="Exit Solo  [F1]" if active else "Enter Solo  [F1]",
            icon='HIDE_OFF' if active else 'HIDE_ON',
        )

        layout.separator()
        layout.label(text="Include with Solo:", icon='OPTIONS')

        box = layout.box()
        box.prop(props, "include_collections", icon='OUTLINER_COLLECTION')
        box.prop(props, "include_instance_collections", icon='OBJECT_DATA')

        layout.separator()
        layout.label(text="How to use:", icon='INFO')

        col = layout.column(align=True)
        col.scale_y = 0.8
        col.label(text="1. Select object(s)")
        col.label(text="2. Click Enter Solo or press F1")
        col.label(text="3. Press F1 again to restore")
        col.label(text="4. Re-select objects for new set")

        layout.separator()
        layout.separator()

        credit = layout.column()
        credit.scale_y = 0.55
        credit.enabled = False
        credit.label(text="by Vincent Ilagan")


# ---------------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------------

classes = (
    SoloModeProperties,
    OBJECT_OT_solo_mode_toggle,
    VIEW3D_PT_solo_mode_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.solo_mode_props = bpy.props.PointerProperty(
        type=SoloModeProperties
    )

    bpy.types.VIEW3D_HT_header.append(draw_solo_header)
    register_keymap()


def unregister():
    unregister_keymap()

    bpy.types.VIEW3D_HT_header.remove(draw_solo_header)

    if hasattr(bpy.types.Scene, "solo_mode_props"):
        del bpy.types.Scene.solo_mode_props

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()