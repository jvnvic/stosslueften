# Loads OpenFOAM v2606 into the current shell: the Ubuntu package or the Arch AUR build.
# Used by the other scripts:  source hpc/setup/foam_env.sh
for _foam_bashrc in /usr/lib/openfoam/openfoam2606/etc/bashrc /opt/OpenFOAM/OpenFOAM-v2606/etc/bashrc; do
    if [ -f "$_foam_bashrc" ]; then
        # OpenFOAM's bashrc does not work with `set -e` or `set -u`: switch them off while loading it
        _foam_flags=$-
        set +eu
        source "$_foam_bashrc"
        case $_foam_flags in *e*) set -e ;; esac
        case $_foam_flags in *u*) set -u ;; esac
        break
    fi
done
unset _foam_bashrc _foam_flags
if [ -z "${WM_PROJECT_DIR:-}" ]; then
    echo "OpenFOAM v2606 not found (looked in /usr/lib/openfoam/openfoam2606 and /opt/OpenFOAM/OpenFOAM-v2606)" >&2
    return 1 2>/dev/null || exit 1
fi
