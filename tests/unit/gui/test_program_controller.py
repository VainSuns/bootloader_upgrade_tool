from __future__ import annotations

from dataclasses import dataclass

from bootloader_upgrade_tool.gui.program_controller import (
    LoadImageRequest,
    ProgramController,
    ProgramControllerDependencies,
    RunRequest,
)
from bootloader_upgrade_tool.images import ImageIdentity


@dataclass(frozen=True)
class FakeImage:
    identity: ImageIdentity


@dataclass(frozen=True)
class FakeResult:
    ok: bool = True
    summary: dict[str, object] | None = None


class FakeOps:
    def __init__(self, *, same_image: bool = False) -> None:
        self.identity = ImageIdentity(0x082400, 16, 0x12345678, 0x082410)
        self.image = FakeImage(self.identity)
        self.service = object()
        self.calls: list[str] = []
        self.same_image = same_image

    def deps(self) -> ProgramControllerDependencies:
        return ProgramControllerDependencies(
            prepare_flash_app_image=self.prepare_flash_app_image,
            prepare_service_image=self.prepare_service_image,
            get_metadata_summary=self.get_metadata_summary,
            erase_flash_image_area=self.record("erase_flash_image_area"),
            program_flash_image=self.record("program_flash_image"),
            verify_flash_image=self.record("verify_flash_image"),
            append_image_valid=self.record("append_image_valid"),
            append_boot_attempt=self.record("append_boot_attempt"),
            append_app_confirmed=self.record("append_app_confirmed"),
            run_flash_app=self.record("run_flash_app"),
        )

    def prepare_flash_app_image(self, *args, **kwargs) -> FakeImage:
        self.calls.append("prepare_flash_app_image")
        return self.image

    def prepare_service_image(self, *args, **kwargs) -> object:
        self.calls.append("prepare_service_image")
        return self.service

    def get_metadata_summary(self, ctx) -> FakeResult:
        self.calls.append("get_metadata_summary")
        identity = self.identity
        summary = {
            "metadata_valid": 1,
            "entry_point": identity.entry_point,
            "image_size_words": identity.image_size_words,
            "image_crc32": identity.image_crc32,
        }
        if not self.same_image:
            summary["image_crc32"] = 0
        return FakeResult(summary=summary)

    def record(self, name: str):
        def operation(*args, **kwargs) -> FakeResult:
            self.calls.append(name)
            return FakeResult()

        return operation


def load_request(ops: FakeOps, **kwargs) -> LoadImageRequest:
    return LoadImageRequest(object(), "app.out", "service.out", "service.map", **kwargs)


def run_request(ops: FakeOps, **kwargs) -> RunRequest:
    return RunRequest(object(), ops.identity, ops.identity.entry_point, service=ops.service, **kwargs)


def test_load_image_sequence_order_is_correct() -> None:
    ops = FakeOps()
    result = ProgramController(ops.deps()).load_image_cpu1(load_request(ops))

    assert result.ok
    assert ops.calls == [
        "prepare_flash_app_image",
        "prepare_service_image",
        "get_metadata_summary",
        "erase_flash_image_area",
        "program_flash_image",
        "verify_flash_image",
        "append_image_valid",
    ]


def test_verify_flash_image_happens_before_append_image_valid() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).load_image_cpu1(load_request(ops))

    assert ops.calls.index("verify_flash_image") < ops.calls.index("append_image_valid")


def test_load_image_without_auto_run_does_not_run_or_append_run_metadata() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).load_image_cpu1(load_request(ops, auto_run_after_load=False, confirm_app=True))

    assert "append_boot_attempt" not in ops.calls
    assert "append_app_confirmed" not in ops.calls
    assert "run_flash_app" not in ops.calls


def test_same_image_without_force_load_skips_write_steps() -> None:
    ops = FakeOps(same_image=True)
    result = ProgramController(ops.deps()).load_image_cpu1(load_request(ops, force_load=False))

    assert result.status == "skipped"
    assert "erase_flash_image_area" not in ops.calls
    assert "program_flash_image" not in ops.calls
    assert "verify_flash_image" not in ops.calls
    assert "append_image_valid" not in ops.calls


def test_same_image_with_force_load_performs_full_load_sequence() -> None:
    ops = FakeOps(same_image=True)
    ProgramController(ops.deps()).load_image_cpu1(load_request(ops, force_load=True))

    assert "erase_flash_image_area" in ops.calls
    assert "program_flash_image" in ops.calls
    assert "verify_flash_image" in ops.calls
    assert "append_image_valid" in ops.calls


def test_auto_run_after_load_calls_run_sequence_after_append_image_valid() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).load_image_cpu1(load_request(ops, auto_run_after_load=True, confirm_app=True))

    assert ops.calls == [
        "prepare_flash_app_image",
        "prepare_service_image",
        "get_metadata_summary",
        "erase_flash_image_area",
        "program_flash_image",
        "verify_flash_image",
        "append_image_valid",
        "get_metadata_summary",
        "append_boot_attempt",
        "append_app_confirmed",
        "run_flash_app",
    ]


def test_run_without_confirm_app_calls_boot_attempt_before_run() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).run_cpu1(run_request(ops, confirm_app=False))

    assert ops.calls == ["get_metadata_summary", "append_boot_attempt", "run_flash_app"]


def test_run_with_confirm_app_orders_metadata_before_run() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).run_cpu1(run_request(ops, confirm_app=True))

    assert ops.calls == [
        "get_metadata_summary",
        "append_boot_attempt",
        "append_app_confirmed",
        "run_flash_app",
    ]


def test_app_confirmed_is_never_called_after_run_flash_app() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).run_cpu1(run_request(ops, confirm_app=True))

    assert ops.calls.index("append_app_confirmed") < ops.calls.index("run_flash_app")


def test_service_attach_is_not_exposed_as_public_controller_action() -> None:
    public = {name for name in dir(ProgramController) if not name.startswith("_")}

    assert public == {"load_image_cpu1", "run_cpu1"}
    assert "service_attach" not in public


def test_cooperative_cancel_stops_before_next_operation_step() -> None:
    ops = FakeOps()
    checks = iter([False, False, True])
    result = ProgramController(ops.deps()).load_image_cpu1(
        load_request(ops),
        should_cancel=lambda: next(checks, True),
    )

    assert result.status == "cancelled"
    assert ops.calls == ["prepare_flash_app_image", "prepare_service_image", "get_metadata_summary"]


def test_run_stage_is_not_cancelable_once_started() -> None:
    ops = FakeOps()
    checks = iter([False, True, True])
    result = ProgramController(ops.deps()).run_cpu1(
        run_request(ops, confirm_app=True),
        should_cancel=lambda: next(checks, True),
    )

    assert result.ok
    assert ops.calls == [
        "get_metadata_summary",
        "append_boot_attempt",
        "append_app_confirmed",
        "run_flash_app",
    ]


def test_tests_use_only_injected_fakes_for_hardware_touching_steps() -> None:
    ops = FakeOps()
    ProgramController(ops.deps()).load_image_cpu1(load_request(ops, auto_run_after_load=True))

    assert all("serial" not in call.lower() for call in ops.calls)
    assert all("subprocess" not in call.lower() for call in ops.calls)
    assert all("hex2000" not in call.lower() for call in ops.calls)
