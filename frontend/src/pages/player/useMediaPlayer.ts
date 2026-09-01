import { useEffect, useRef, useState, type RefObject } from 'react';
import Artplayer from 'artplayer';
import type { FileEntry } from '../../api/types';
import { withAuthUrl } from '../../shared/media';

export type VideoFit = 'cover' | 'contain';

interface MediaPlayer {
  containerRef: RefObject<HTMLDivElement | null>;
  videoFit: VideoFit;
  videoAspectRatio: number;
  setVideoFit: (fit: VideoFit) => void;
}

export function useMediaPlayer(active: FileEntry | null, token: string): MediaPlayer {
  const [videoFit, setVideoFitState] = useState<VideoFit>('contain');
  const [videoAspectRatio, setVideoAspectRatio] = useState(16 / 9);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const artRef = useRef<Artplayer | null>(null);

  function setVideoFit(nextFit: VideoFit) {
    setVideoFitState(nextFit);
    containerRef.current?.style.setProperty('--video-fit', nextFit);
  }

  useEffect(() => {
    if (!containerRef.current || !active) return;
    artRef.current?.destroy(false);
    artRef.current = new Artplayer({
      container: containerRef.current,
      url: withAuthUrl(active.stream_url, token),
      type: active.media_type === 'audio' ? 'audio' : 'mp4',
      autoplay: true,
      setting: true,
      playbackRate: false,
      controls: [{
        position: 'right',
        html: '倍速',
        selector: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((rate) => ({ html: `${rate}x`, value: rate, default: rate === 1 })),
        onSelect: (item: { value?: string | number }) => {
          const rate = Number(item.value || 1);
          if (artRef.current) artRef.current.playbackRate = rate;
          return `${rate}x`;
        },
      }],
      aspectRatio: false,
      fullscreen: true,
      fullscreenWeb: true,
      hotkey: true,
      pip: active.media_type === 'video',
      mutex: true,
      moreVideoAttr: { preload: 'metadata' },
    });
    containerRef.current.style.setProperty('--video-fit', videoFit);
    const updateVideoRatio = () => {
      const { videoWidth, videoHeight } = artRef.current?.video || {};
      if (videoWidth && videoHeight) setVideoAspectRatio(videoWidth / videoHeight);
    };
    artRef.current.video.addEventListener('loadedmetadata', updateVideoRatio);
    updateVideoRatio();
    return () => {
      artRef.current?.video.removeEventListener('loadedmetadata', updateVideoRatio);
      artRef.current?.destroy(false);
      artRef.current = null;
    };
  }, [active?.id, token]);

  useEffect(() => {
    containerRef.current?.style.setProperty('--video-fit', videoFit);
  }, [videoFit]);

  return { containerRef, videoFit, videoAspectRatio, setVideoFit };
}
