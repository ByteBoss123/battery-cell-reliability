"""NHTSA client behaviour against a fake transport (no network in CI)."""
from cellrel.ingest.nhtsa import Nameplate, NhtsaClient, normalize_complaint

C = {"odiNumber": 1, "dateOfIncident": "03/15/2021", "dateComplaintFiled": "04/01/2021", "components": "ELECTRICAL SYSTEM:PROPULSION SYSTEM:TRACTION BATTERY",
     "summary": "Car lost power", "fire": True, "crash": False, "numberOfInjuries": 0}


def fake(responses):
    calls = []

    def get(path):
        calls.append(path)
        return responses(path, len(calls))
    return get, calls


def test_normalize_complaint_flags_and_dates():
    r = normalize_complaint(C, "B", 2019)
    assert r == {"model": "B", "my": 19, "odi": 1, "incident_ym": "202103", "filed_ym": "202104", "flags": "1010", "injuries": 0}


def test_retries_on_rate_limit_then_succeeds():
    get, calls = fake(lambda p, i: (429, None) if i == 1 else (200, {"results": []}))
    assert NhtsaClient(get=get, backoff_s=0, pause_s=0).get("/x") == {"results": []}
    assert len(calls) == 2


def test_400_with_empty_body_is_no_data_not_error():
    get, _ = fake(lambda p, i: (400, {"count": 0, "results": []}))
    assert NhtsaClient(get=get, backoff_s=0, pause_s=0).get("/x")["results"] == []


def test_name_variants_discovered_and_deduplicated():
    def resp(path, i):
        if path.startswith("/products"):
            return 200, {"results": [{"model": "BOLT"}, {"model": "BOLT EV"}, {"model": "CAMARO"}]}
        if path.startswith("/complaints"):
            return 200, {"results": [C]}               # same complaint listed under both names
        return 200, {"results": []}
    get, calls = fake(resp)
    comp, _ = NhtsaClient(get=get, backoff_s=0, pause_s=0).pull([Nameplate("B", "chevrolet", r"^BOLT( EV| EUV)?$", (2019, 2019))])
    assert len(comp) == 1
    assert not any("CAMARO" in c for c in calls)
