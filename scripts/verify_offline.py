"""Check all mandatory Windows CPython 3.12 dependencies in the offline wheels."""
from email import message_from_bytes
from pathlib import Path
from zipfile import ZipFile
from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.markers import default_environment
from pip._vendor.packaging.utils import canonicalize_name

root = Path(__file__).resolve().parents[1]
wheels = {}
for path in (root / 'wheelhouse').glob('*.whl'):
    with ZipFile(path) as archive:
        assert archive.testzip() is None, path.name
        metadata = message_from_bytes(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))))
        wheels[canonicalize_name(metadata['Name'])] = (metadata['Version'], metadata.get_all('Requires-Dist', []))
environment = {**default_environment(), 'python_version': '3.12', 'python_full_version': '3.12.10',
               'sys_platform': 'win32', 'os_name': 'nt', 'platform_system': 'Windows',
               'platform_machine': 'AMD64', 'extra': ''}
requirements = [line for line in (root / 'requirements.txt').read_text().splitlines() if line and not line.startswith('#')]
requirements += [dependency for _, dependencies in wheels.values() for dependency in dependencies]
for line in requirements:
    requirement = Requirement(line)
    if requirement.marker is None or requirement.marker.evaluate(environment):
        name = canonicalize_name(requirement.name)
        assert name in wheels, f'Missing Windows dependency: {line}'
        assert wheels[name][0] in requirement.specifier, f'Wrong version: {line}'
print(f'Windows Python 3.12 x64: {len(wheels)} wheels, all mandatory dependencies and ZIP checks passed.')
