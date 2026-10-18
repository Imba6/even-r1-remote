"""Collect installed dependency notices for redistributable builds."""
from importlib.metadata import distributions
from pathlib import Path
out=Path('dist/notices'); out.mkdir(parents=True,exist_ok=True)
for dist in distributions():
    name=dist.metadata.get('Name','unknown')
    for file in dist.files or []:
        if any(word in str(file).lower() for word in ('license','copying','copyright','notice')):
            source=Path(dist.locate_file(file))
            if source.is_file():
                target=out/name/str(file).replace('..','_')
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(source.read_bytes())
print('Dependency notices collected')
