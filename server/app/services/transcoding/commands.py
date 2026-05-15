"""FFmpeg HLS command construction."""

from dataclasses import dataclass

from app.services.transcoding.hardware import HardwareAcceleration


@dataclass(slots=True)
class HlsCommandOptions:
    """Inputs required to build a transcoding command."""

    input_path: str
    playlist_path: str
    segment_pattern: str
    video_codec: str = "h264"
    audio_codec: str = "aac"
    video_bitrate: int | None = None
    audio_bitrate: int | None = None
    max_width: int | None = None
    max_height: int | None = None
    segment_duration: int = 6
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    is_image_subtitle: bool = False
    start_time: float | None = None
    hls_segment_type: str = "mpegts"


class HlsCommandBuilder:
    """Build ffmpeg commands for generated HLS playback."""

    def __init__(self, ffmpeg_path: str, hw_accel: HardwareAcceleration):
        self.ffmpeg_path = ffmpeg_path
        self.hw_accel = hw_accel

    def build_remux(
        self,
        input_path: str,
        playlist_path: str,
        segment_pattern: str,
        segment_duration: int = 6,
        audio_stream_index: int | None = None,
        start_time: float | None = None,
        hls_segment_type: str = "mpegts",
    ) -> list[str]:
        """Build an HLS remux command with stream copy."""
        cmd = [self.ffmpeg_path, "-hide_banner", "-y"]
        self._append_seek_and_input(cmd, input_path, start_time)

        if audio_stream_index is not None:
            cmd.extend(["-map", "0:v:0", "-map", f"0:{audio_stream_index}"])
        else:
            cmd.extend(["-map", "0:v:0", "-map", "0:a?"])

        cmd.extend(["-c", "copy", "-copyts", "-start_at_zero", "-avoid_negative_ts", "make_zero"])
        cmd.extend(
            self._hls_args(
                segment_duration,
                segment_pattern,
                playlist_path,
                independent_segments=False,
                segment_type=hls_segment_type,
            )
        )
        return cmd

    def build_transcode(self, options: HlsCommandOptions) -> list[str]:
        """Build an HLS command that can transcode video, audio, or both."""
        cmd = [self.ffmpeg_path, "-hide_banner", "-y"]

        if self.hw_accel.vaapi_available and self.hw_accel.vaapi_device and options.video_codec != "copy":
            cmd.extend(["-vaapi_device", self.hw_accel.vaapi_device])

        self._append_seek_and_input(cmd, options.input_path, options.start_time)

        encoder, encoder_args = self.hw_accel.get_video_encoder(options.video_codec)
        cmd.extend(["-c:v", encoder])
        if encoder != "copy":
            cmd.extend(encoder_args)
            if "vaapi" not in encoder:
                cmd.extend(["-pix_fmt", "yuv420p"])
            cmd.extend(["-force_key_frames", f"expr:gte(t,n_forced*{options.segment_duration})"])

        cmd.extend(["-c:a", options.audio_codec])
        if options.audio_codec == "aac":
            cmd.extend(["-profile:a", "aac_low", "-ar", "48000", "-ac", "2"])
        if options.audio_bitrate and options.audio_codec != "copy":
            cmd.extend(["-b:a", str(options.audio_bitrate)])

        if options.video_bitrate and encoder != "copy":
            cmd.extend([
                "-b:v",
                str(options.video_bitrate),
                "-maxrate",
                str(int(options.video_bitrate * 1.2)),
                "-bufsize",
                str(options.video_bitrate * 2),
            ])

        vf_filters = self._video_filters(options, encoder)
        if options.subtitle_stream_index is not None and encoder != "copy":
            self._append_subtitle_filters(cmd, options, encoder, vf_filters)
        else:
            self._append_default_maps(cmd, options.audio_stream_index)
            if vf_filters and encoder != "copy":
                cmd.extend(["-vf", ",".join(vf_filters)])

        cmd.extend(["-copyts", "-start_at_zero"])
        cmd.extend(
            self._hls_args(
                options.segment_duration,
                options.segment_pattern,
                options.playlist_path,
                independent_segments=encoder != "copy",
                segment_type=options.hls_segment_type,
            )
        )
        return cmd

    def _append_subtitle_filters(
        self,
        cmd: list[str],
        options: HlsCommandOptions,
        encoder: str,
        vf_filters: list[str],
    ) -> None:
        if options.is_image_subtitle:
            software_filters = [
                item for item in vf_filters if "vaapi" not in item and item != "hwupload" and item != "format=nv12"
            ]
            filter_input = f"[0:v]{','.join(software_filters)}[v]" if software_filters else "[0:v]null[v]"
            cmd.extend([
                "-filter_complex",
                f"{filter_input};[v][0:{options.subtitle_stream_index}]overlay[vout]",
                "-map",
                "[vout]",
            ])
            self._append_audio_map(cmd, options.audio_stream_index)
            return

        subtitle_filter = f"subtitles='{options.input_path}':stream_index={options.subtitle_stream_index}"
        if "vaapi" in encoder:
            vf_filters.insert(0, subtitle_filter)
        else:
            vf_filters.append(subtitle_filter)

        self._append_default_maps(cmd, options.audio_stream_index)
        cmd.extend(["-vf", ",".join(vf_filters)])

    def _video_filters(self, options: HlsCommandOptions, encoder: str) -> list[str]:
        filters: list[str] = []
        if "vaapi" in encoder:
            filters.extend(["format=nv12", "hwupload"])

        if (options.max_width or options.max_height) and encoder != "copy":
            scale = "scale_vaapi" if "vaapi" in encoder else "scale"
            if options.max_width and options.max_height:
                filters.append(
                    f"{scale}=w={options.max_width}:h={options.max_height}:"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2"
                )
            elif options.max_width:
                filters.append(f"{scale}=w={options.max_width}:h=-2")
            else:
                filters.append(f"{scale}=w=-2:h={options.max_height}")

        return filters

    def _append_default_maps(self, cmd: list[str], audio_stream_index: int | None) -> None:
        cmd.extend(["-map", "0:v:0"])
        self._append_audio_map(cmd, audio_stream_index)

    def _append_audio_map(self, cmd: list[str], audio_stream_index: int | None) -> None:
        if audio_stream_index is not None:
            cmd.extend(["-map", f"0:{audio_stream_index}"])
        else:
            cmd.extend(["-map", "0:a:0?"])

    def _append_seek_and_input(self, cmd: list[str], input_path: str, start_time: float | None) -> None:
        if start_time and start_time > 0:
            cmd.extend(["-ss", str(start_time)])
        cmd.extend(["-i", input_path])

    def _hls_args(
        self,
        segment_duration: int,
        segment_pattern: str,
        playlist_path: str,
        independent_segments: bool,
        segment_type: str = "mpegts",
    ) -> list[str]:
        args = [
            "-max_muxing_queue_size",
            "2048",
            "-f",
            "hls",
            "-hls_time",
            str(segment_duration),
            "-hls_playlist_type",
            "event",
            "-hls_list_size",
            "0",
            "-hls_segment_type",
            segment_type,
        ]
        if segment_type == "fmp4":
            args.extend(["-hls_fmp4_init_filename", "init.mp4"])
        hls_flags = ["temp_file"]
        if independent_segments:
            hls_flags.append("independent_segments")
        args.extend(["-hls_flags", "+".join(hls_flags)])
        args.extend([
            "-hls_segment_filename",
            segment_pattern,
            "-start_number",
            "0",
            "-hls_allow_cache",
            "1",
            playlist_path,
        ])
        return args
