from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
BOOTSTRAP = REPO / "infra" / "prod" / "bootstrap.sh"


def test_production_bootstrap_stages_changed_step_ca_root() -> None:
    script = BOOTSTRAP.read_text(encoding="utf-8")

    export = '> "$STEP_CA_ROOT_TMP"'
    compare = 'cmp -s "$STEP_CA_ROOT" "$STEP_CA_ROOT_NEXT"'
    validate = '"$REPO_ROOT/infra/validate/validate-production-vault-tls.sh"'

    assert 'STEP_CA_ROOT="$SECRETS_DIR/step-ca-root.crt"' in script
    assert 'STEP_CA_ROOT_NEXT="${STEP_CA_ROOT}.next"' in script
    assert (
        'STEP_CA_ROOT_TMP=$(mktemp "$SECRETS_DIR/.step-ca-root.crt.XXXXXX")'
        in script
    )
    assert "trap 'rm -f \"$STEP_CA_ROOT_TMP\"' EXIT" in script
    assert export in script
    assert 'chmod 0600 "$STEP_CA_ROOT_TMP"' in script
    assert 'mv "$STEP_CA_ROOT_TMP" "$STEP_CA_ROOT_NEXT"' in script
    assert 'active step-ca trust bundle must be a regular file' in script
    assert 'staged step-ca root must be a regular file' in script
    assert 'openssl x509 -in "$STEP_CA_ROOT_TMP" -noout' in script
    assert 'if [ ! -f "$STEP_CA_ROOT" ]; then' in script
    assert 'mv "$STEP_CA_ROOT_NEXT" "$STEP_CA_ROOT"' in script
    assert compare in script
    assert 'rm -f "$STEP_CA_ROOT_NEXT"' in script
    assert "active trust bundle was not replaced" in script
    assert script.index(export) < script.index(compare) < script.index(validate)
    assert '> "$SECRETS_DIR/step-ca-root.crt"' not in script
