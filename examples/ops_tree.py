"""Tree operations: add, add_external, find, find_by_name, remove, subtree.

Ids are free-form strings (`new_id()` mints a UUIDv7 when none is given); names
need not be unique, so `find` takes an id and `find_by_name` returns a tuple.

Run with: pixi run --environment dev python examples/ops_tree.py
"""

import ngio_collections as ngc
from _ids import uid
from _images import image


def main() -> None:
    root = ngc.new_collection(id=uid(1), name="root")
    plate = ngc.new_collection(id=uid(2), name="plate")
    root = root.add(plate)  # edits return the new root

    # An image is linked through a declaring entry (its own document) ...
    entry = ngc.new_node(
        "multiscale", id=uid(3), name="image", path=ngc.ZarrPath(href="./image")
    )
    root = root.find(uid(2)).add_external(entry)
    # ... or inlined: `add` embeds a multiscale that has no path.
    root = root.add(image(9, "thumbnail"))
    print("inlined     :", root.find(uid(9)).name, root.find(uid(9)).is_external)

    # No id given: `new_id()` mints a UUIDv7 for each; any id string would do.
    root = root.add(
        ngc.new_collection(name="scratch"), ngc.new_collection(name="scratch")
    )
    print("walk        :", [(n.name, n.id[-4:]) for n in root.walk()])
    print("find(id)    :", root.find(uid(3)).name, root.find(uid(3)).parent().name)
    print("find_by_name:", [n.id[-4:] for n in root.find_by_name("scratch")])

    sub = root.find(uid(2)).subtree()
    print("subtree     :", [n.name for n in sub.walk()], "detached:", sub.is_detached)
    pruned = root.find(uid(2)).remove()
    print("after remove:", [n.name for n in pruned.walk()])
    print("original    :", [n.name for n in root.walk()])


if __name__ == "__main__":
    main()
