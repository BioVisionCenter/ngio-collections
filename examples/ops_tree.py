"""Tree operations: add, add_external, find, find_by_name, remove, subtree.

Ids are UUIDs (`new_id()` mints a UUIDv7); names are free-form and need not be
unique, so `find` takes a UUID and `find_by_name` returns a tuple.

Run with: pixi run python examples/ops_tree.py
"""

import ngio_collections as ngc
from _ids import uid


def main() -> None:
    root = ngc.new_collection(id=uid(1), name="root")
    plate = ngc.new_collection(id=uid(2), name="plate")
    root = root.add(plate)  # edits return the new root

    # Multiscales are never embedded: link a declaring entry instead.
    entry = ngc.new_node(
        "multiscale", id=uid(3), name="image", path=ngc.ZarrPath(href="./image")
    )
    root = root.find(uid(2)).add_external(entry)
    try:
        root.add(ngc.new_multiscale(coordinate_systems=[], scales=[]))
    except ngc.NodeStateError as error:
        print("embedding refused:", str(error)[:60], "...")

    root = root.add(
        ngc.new_collection(name="scratch"), ngc.new_collection(name="scratch")
    )
    print("walk        :", [(n.name, n.id[-4:]) for n in root.walk()])
    print("find(uuid)  :", root.find(uid(3)).name, root.find(uid(3)).parent().name)
    print("find_by_name:", [n.id[-4:] for n in root.find_by_name("scratch")])

    sub = root.find(uid(2)).subtree()
    print("subtree     :", [n.name for n in sub.walk()], "detached:", sub.is_detached)
    pruned = root.find(uid(2)).remove()
    print("after remove:", [n.name for n in pruned.walk()])
    print("original    :", [n.name for n in root.walk()])


if __name__ == "__main__":
    main()
