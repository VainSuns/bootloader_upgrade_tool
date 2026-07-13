"""Flash erase/program/verify operations."""

from __future__ import annotations

from dataclasses import dataclass

from ..core.workflow import _prepare_packets
from ..images.models import PreparedFlashImage
from ._flash_protocol import (
    erase_protocol,
    program_begin_protocol,
    program_data_protocol,
    program_end_protocol,
    verify_begin_protocol,
    verify_data_protocol,
    verify_end_protocol,
)
from ._service_runtime import ensure_service_attached
from .context import FlashOperationContext
from .results import OperationFailure, ProgressEvent, emit_progress, failure_result, ok_result, service_summary_dict


@dataclass(frozen=True)
class EraseFlashImageAreaRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class EraseSectorMaskRequest:
    sector_mask: int


@dataclass(frozen=True)
class ProgramFlashImageRequest:
    image: PreparedFlashImage


@dataclass(frozen=True)
class VerifyFlashImageRequest:
    image: PreparedFlashImage


def _check_sector_mask(ctx: FlashOperationContext, sector_mask: int) -> None:
    flash = ctx.target.memory_map.flash
    if sector_mask == 0:
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask must be nonzero", stage="ERASE")
    if flash is not None and (sector_mask & flash.forbidden_erase_mask):
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask includes forbidden sectors", stage="ERASE")
    if flash is not None and (sector_mask & ~flash.allowed_erase_mask):
        raise OperationFailure("FORBIDDEN_SECTOR", "sector mask includes sectors outside allowed erase mask", stage="ERASE")


def erase_flash_image_area(ctx: FlashOperationContext, request: EraseFlashImageAreaRequest):
    operation = "erase_flash_image_area"
    try:
        service = ensure_service_attached(ctx)
        flash = ctx.target.memory_map.flash
        metadata_mask = 0 if flash is None else flash.metadata_sector_mask
        effective = request.image.sector_mask | metadata_mask
        _check_sector_mask(ctx, effective)
        erased: list[int] = []
        if metadata_mask:
            erase_protocol(ctx, sector_mask=metadata_mask)
            erased.append(metadata_mask)
        rest = effective & ~metadata_mask
        if rest:
            erase_protocol(ctx, sector_mask=rest)
            erased.append(rest)
        return ok_result(
            ctx,
            operation,
            "ERASE",
            {"erased_masks": erased},
            details={"effective_mask": effective},
            service=service_summary_dict(service),
        )
    except Exception as exc:
        return failure_result(ctx, operation, "ERASE", exc)


def erase_sector_mask(ctx: FlashOperationContext, request: EraseSectorMaskRequest):
    operation = "erase_sector_mask"
    try:
        service = ensure_service_attached(ctx)
        _check_sector_mask(ctx, request.sector_mask)
        erase_protocol(ctx, sector_mask=request.sector_mask)
        return ok_result(
            ctx,
            operation,
            "ERASE",
            {"erased_masks": [request.sector_mask]},
            service=service_summary_dict(service),
        )
    except Exception as exc:
        return failure_result(ctx, operation, "ERASE", exc)


def _transfer(
    ctx: FlashOperationContext,
    request_image: PreparedFlashImage,
    *,
    operation: str,
    verify: bool,
    max_data_words: int,
):
    packets = _prepare_packets(request_image.image, max_data_words)
    total_words = sum(len(packet.words) for packet in packets)
    begin = verify_begin_protocol if verify else program_begin_protocol
    data = verify_data_protocol if verify else program_data_protocol
    end = verify_end_protocol if verify else program_end_protocol
    begin(ctx, packet_count=len(packets), total_words=total_words, entry_point=request_image.identity.entry_point)
    sent = 0
    stage = "VERIFY_DATA" if verify else "PROGRAM_DATA"
    for packet in packets:
        data(ctx, address=packet.address, words=packet.words, packet_index=packet.index)
        sent += len(packet.words)
        emit_progress(
            ctx,
            ProgressEvent(operation, ctx.target.name, stage, stage, sent, total_words, len(packet.words)),
        )
    end(ctx, packet_count=len(packets), total_words=total_words)
    return {"total_words": total_words, "packets": len(packets)}


def program_flash_image(ctx: FlashOperationContext, request: ProgramFlashImageRequest):
    operation = "program_flash_image"
    try:
        max_data_words = ctx.session.client.effective_max_write_data_words
        service = ensure_service_attached(ctx)
        summary = _transfer(ctx, request.image, operation=operation, verify=False, max_data_words=max_data_words)
        return ok_result(ctx, operation, "PROGRAM_END", summary, service=service_summary_dict(service))
    except Exception as exc:
        return failure_result(ctx, operation, "PROGRAM", exc)


def verify_flash_image(ctx: FlashOperationContext, request: VerifyFlashImageRequest):
    operation = "verify_flash_image"
    try:
        max_data_words = ctx.session.client.effective_max_write_data_words
        service = ensure_service_attached(ctx)
        summary = _transfer(ctx, request.image, operation=operation, verify=True, max_data_words=max_data_words)
        return ok_result(ctx, operation, "VERIFY_END", summary, service=service_summary_dict(service))
    except Exception as exc:
        return failure_result(ctx, operation, "VERIFY", exc)
