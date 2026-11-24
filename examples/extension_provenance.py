"""The smallest extension: one metadata trait on a collection entry.

RFC-8 revision 2 identifies extension types by URI and requires every extension
a document uses to be listed in its `extensionManifest`. The Fractal
*provenance* trait (see `_extensions.py`) records which task produced a node
and from which inputs. Three things to see:

* `register_extension` is all the library needs: the manifest entry is derived
  from the traits the document actually uses when it is written;
* the trait sits on the collection's *entry*, so the image document is never
  touched;
* an undeclared URI type is a validation finding.

Run with: pixi run --environment dev python examples/extension_provenance.py
"""

from pathlib import Path

import ngio_collections as ngc
from _extensions import FRACTAL_ENTRY, PROVENANCE
from _ids import uid
from _images import image


def main() -> None:
    base = Path(__file__).parent / "data" / Path(__file__).stem
    url = str(base / "zarr.json")
    ngc.register_extension(FRACTAL_ENTRY)

    raw = ngc.create(str(base / "raw"), image(2, "raw"), overwrite=True)
    nuclei = ngc.create(str(base / "nuclei"), image(3, "nuclei"), overwrite=True)
    nuclei = nuclei.set_trait(  # on the entry, not in nuclei/zarr.json
        {
            "type": PROVENANCE,
            "task": "cellpose-segmentation",
            "version": "0.4.2",
            "timestamp": "2026-10-27T10:00:00Z",
            "inputs": [{"type": "multiscale", "ref": uid(2)}],
        }
    )
    root = ngc.new_collection(id=uid(1), name="experiment").add_external(raw, nuclei)
    ngc.create(url, root, overwrite=True)
    print(Path(url).read_text())  # note the derived `extensionManifest`

    view = ngc.open_resolved(url)
    print("provenance :", view.find(uid(3)).traits[PROVENANCE]["task"])
    print("validation :", view.validate(ngc.ALL_VALIDATORS))

    undeclared = ngc.open(url).set_trait({"type": "https://unknown.example/x", "a": 1})
    print(
        "undeclared :",
        [e.validator for e in undeclared.validate(ngc.CORE_VALIDATORS)],
    )


if __name__ == "__main__":
    main()
