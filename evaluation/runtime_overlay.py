"""Verified local runtime overlay for the existing bounded Docker launcher."""
from pathlib import Path

from scripts.download_models import sha256


def with_runtime_overlay(command, overlay):
    """Keep image, devices and resource limits; replace only executable/libraries."""
    if not overlay:
        return list(command)
    binary_dir = Path(overlay['bin_directory']).resolve(strict=True)
    expected = overlay['sha256']
    if not expected or 'llama-server' not in expected:
        raise ValueError('runtime overlay requires executable and library hashes')
    actual_files = {p.name for p in binary_dir.iterdir() if p.is_file()
                    and ('.so' in p.name or p.name == 'llama-server')}
    if set(expected) != actual_files:
        raise ValueError('runtime overlay inventory mismatch')
    for name, checksum in expected.items():
        if sha256(binary_dir / name) != checksum:
            raise ValueError(f'runtime overlay hash mismatch: {name}')
    result = list(command)
    result[3:3] = ['--entrypoint', '/sabakan-runtime/llama-server',
                   '-v', f'{binary_dir}:/sabakan-runtime:ro']
    for index, value in enumerate(result):
        if value.startswith('LD_LIBRARY_PATH='):
            result[index] = value.replace('LD_LIBRARY_PATH=', 'LD_LIBRARY_PATH=/sabakan-runtime:', 1)
            break
    else:
        raise ValueError('expected CUDA library environment is absent')
    return result
