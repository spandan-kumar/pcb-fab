import { useMemo } from 'react'
import * as THREE from 'three'

const cache = new Map<string, { tex: THREE.CanvasTexture; aspect: number }>()

function getTex(text: string, color: string, weight: number) {
  const key = `${text}|${color}|${weight}`
  const hit = cache.get(key)
  if (hit) return hit
  const c = document.createElement('canvas')
  const ctx = c.getContext('2d')!
  const fs = 64
  const font = `${weight} ${fs}px "JetBrains Mono", ui-monospace, Menlo, monospace`
  ctx.font = font
  const w = Math.max(8, Math.ceil(ctx.measureText(text).width) + 12)
  c.width = w; c.height = Math.round(fs * 1.3)
  ctx.font = font
  ctx.fillStyle = color
  ctx.textBaseline = 'middle'
  ctx.fillText(text, 6, c.height / 2 + 2)
  const tex = new THREE.CanvasTexture(c)
  tex.minFilter = THREE.LinearMipmapLinearFilter
  tex.magFilter = THREE.LinearFilter
  tex.anisotropy = 4
  tex.colorSpace = THREE.SRGBColorSpace
  const out = { tex, aspect: w / c.height }
  cache.set(key, out)
  return out
}

/** Text rendered via a 2D canvas texture on a plane (no SDF/WebGL side-contexts, no font fetch). `size` is the cap height in world units. */
export function Label({ text, size = 1, color = '#e8eef5', position = [0, 0, 0], rotation = [0, 0, 0], anchorX = 'center', weight = 600, opacity = 1, maxWidth }:
  { text: string; size?: number; color?: string; position?: [number, number, number]; rotation?: [number, number, number]; anchorX?: 'left' | 'center' | 'right'; weight?: number; opacity?: number; maxWidth?: number }) {
  const { tex, aspect } = useMemo(() => getTex(text, color, weight), [text, color, weight])
  let h = size * 1.5
  let w = h * aspect
  if (maxWidth && w > maxWidth) { w = maxWidth; h = w / aspect }
  const ox = anchorX === 'center' ? 0 : anchorX === 'left' ? w / 2 : -w / 2
  return (
    <group position={position} rotation={rotation}>
      <mesh position={[ox, 0, 0]}>
        <planeGeometry args={[w, h]} />
        <meshBasicMaterial map={tex} transparent opacity={opacity} depthWrite={false} toneMapped={false} side={THREE.DoubleSide} />
      </mesh>
    </group>
  )
}
