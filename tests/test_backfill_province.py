def test_province_for_source():
    from scripts.backfill_chroma_province import province_for_source
    slug_map = {"sulu": "Sulu", "davao_del_sur": "Davao del Sur"}
    assert province_for_source("/x/kb/intel/sulu__jolo__4ff64ef9.md", slug_map) == "Sulu"
    assert province_for_source("/x/kb/intel/davao_del_sur__digos__ab.md", slug_map) == "Davao del Sur"
    assert province_for_source("/x/kb/intel/unknown_prov__town__ab.md", slug_map) is None
    assert province_for_source("db:reports:sulu_4ff64ef9", slug_map) is None      # not an intel file
    assert province_for_source("", slug_map) is None
