"""Transparent fixture checks, not a semantic correctness guarantee."""


def grade(case, reply, files):
    answer = reply.get("answer", "")
    missing = [group for group in case.get("required_any",[]) if not any(term.casefold() in answer.casefold() for term in group)]
    exact = answer.casefold().strip().rstrip(".! ") in {value.casefold().strip().rstrip(".! ") for value in case.get("exact_answers",[])}
    missing = [] if exact else missing
    forbidden = [term for term in case.get("forbidden",[]) if term.casefold() in answer.casefold()]
    expected = {(str(files[key].file_id),case["documents"][[d["key"] for d in case["documents"]].index(key)].get("page",1)) for key in case.get("sources",[])}
    actual = {(str(item.get("file_id")),item.get("page")) for item in reply.get("citations",[])}
    errors = []
    if missing:
        errors.append("expected_fact_missing")
    if forbidden:
        errors.append("forbidden_claim")
    if actual != expected:
        errors.append("incorrect_sources")
    return {"passed":not errors,"checks_failed":errors,"source_match":actual==expected}
