#!/bin/bash -l
#SBATCH --nodes=1
#SBATCH --time=2:00:00
{{ sbatch }}
#SBATCH --job-name=mpas_analysis
#SBATCH --output=mpas_analysis.o%j
#SBATCH --error=mpas_analysis.e%j

set -e

{% if use_e3sm_unified %}
source {{ e3sm_unified_script }}

echo E3SM-Unified: {{ e3sm_unified_script }}
{% else %}
source {{ conda_base }}/etc/profile.d/conda.sh
conda activate {{ conda_env }}
export HDF5_USE_FILE_LOCKING=FALSE
export E3SMU_MACHINE={{ machine }}

echo env: {{ conda_env }}
{% endif %}
echo configs: {{ flags }} {{ config }}


{{ parallel_exec }} mpas_analysis --list
{{ parallel_exec }} mpas_analysis --plot_colormaps
{{ parallel_exec }} mpas_analysis --setup_only {{ flags }} {{ config }}
{{ parallel_exec }} mpas_analysis --purge {{ flags }} {{ config }} --verbose
{{ parallel_exec }} mpas_analysis --html_only {{ flags }} {{ config }}

chmod ugo+rx {{ html_base }}/{{ out_common_dir }}
chmod -R ugo+rX {{ html_base }}/{{ out_subdir }}
