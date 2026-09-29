from smp import config, machine


def test_recommended_by_gpu_memory():
    assert machine.recommended(48).name == "xl"
    assert machine.recommended(24).name == "large"
    assert machine.recommended(16).name == "medium"
    assert machine.recommended(0).name == "small"


def test_pick_model_prefers_an_installed_one_that_fits():
    # a 24 GB card: the 32B model is installed but doesn't fit, the 8B one does
    assert machine.pick_model(["qwen3-vl:32b-instruct-q8_0", "qwen3-vl:8b-instruct-q8_0"], 24) == \
        "qwen3-vl:8b-instruct-q8_0"
    assert machine.pick_model([], 24) == "qwen3-vl:30b-a3b-instruct-q4_K_M"
    assert machine.pick_model(["qwen3-vl:8b:latest"], 16) == "qwen3-vl:8b"


def test_installed_models_from_manifests(tmp_path):
    lib = tmp_path / "manifests" / "registry.ollama.ai" / "library" / "qwen3-vl"
    lib.mkdir(parents=True)
    (lib / "8b-instruct-q8_0").write_text("{}")
    other = tmp_path / "manifests" / "registry.ollama.ai" / "someone" / "model"
    other.mkdir(parents=True)
    (other / "latest").write_text("{}")
    assert machine.installed_models(str(tmp_path)) == ["qwen3-vl:8b-instruct-q8_0", "someone/model:latest"]
    assert machine.installed_models(str(tmp_path / "nope")) == []


def test_size_of():
    assert machine.size_of("qwen3-vl:32b-instruct-q8_0") == 36
    assert machine.size_of("unknown") == 0


def test_settings_store_only_choices(data_dir):
    s = config.save({"creator": "Anna", "language": "en", "ollama_exe": ""})
    assert config.stored() == {"creator": "Anna"}           # defaults and empty values aren't stored
    assert s["ollama_url"].endswith(":11436") and s["ollama_models_dir"].endswith("ollama-models")
    config.save({"creator": ""})
    assert config.stored() == {}
