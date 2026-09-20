import * as THREE from 'three'
import { MASK_COLORS, type MaskColor } from '../protocol'

export const copperTop = new THREE.MeshStandardMaterial({ color: '#f2bd66', metalness: 0.8, roughness: 0.3, emissive: '#6a4418', emissiveIntensity: 0.45 })
export const copperBottom = new THREE.MeshStandardMaterial({ color: '#c9975a', metalness: 0.8, roughness: 0.4, emissive: '#2a1a0a', emissiveIntensity: 0.2 })
export const padGold = new THREE.MeshStandardMaterial({ color: '#f0cf85', metalness: 0.95, roughness: 0.25, emissive: '#4a3312', emissiveIntensity: 0.2 })
export const viaMat = new THREE.MeshStandardMaterial({ color: '#d9b47a', metalness: 0.9, roughness: 0.3 })
export const headMat = new THREE.MeshBasicMaterial({ color: '#7ff6ff', toneMapped: false })
export const hoverMat = new THREE.MeshBasicMaterial({ color: '#3ee7ff', toneMapped: false })
export const failMat = new THREE.LineBasicMaterial({ color: '#ff4fa3', transparent: true, opacity: 0.95 })
export const ratsnestMat = new THREE.LineBasicMaterial({ color: '#3ee7ff', transparent: true, opacity: 0.45 })
export const silkMat = new THREE.LineBasicMaterial({ color: '#e8eef5', transparent: true, opacity: 0.85 })
export const drcMat = new THREE.MeshBasicMaterial({ color: '#ff4fa3', toneMapped: false, transparent: true, opacity: 0.9, side: THREE.DoubleSide })

export const bodyBlack = new THREE.MeshStandardMaterial({ color: '#15171b', metalness: 0.1, roughness: 0.55 })
export const bodyDark = new THREE.MeshStandardMaterial({ color: '#23262c', metalness: 0.2, roughness: 0.5 })
export const shieldCan = new THREE.MeshStandardMaterial({ color: '#b9bec6', metalness: 0.9, roughness: 0.35 })
export const capBeige = new THREE.MeshStandardMaterial({ color: '#c8b58a', metalness: 0.05, roughness: 0.7 })
export const resBody = new THREE.MeshStandardMaterial({ color: '#1e1f24', metalness: 0.1, roughness: 0.6 })
export const resTop = new THREE.MeshStandardMaterial({ color: '#dfe3ea', metalness: 0.0, roughness: 0.8 })
export const endCap = new THREE.MeshStandardMaterial({ color: '#d9dde3', metalness: 0.9, roughness: 0.3 })
export const connectorMetal = new THREE.MeshStandardMaterial({ color: '#8e96a2', metalness: 0.75, roughness: 0.48 })
export const plasticBlack = new THREE.MeshStandardMaterial({ color: '#0f1013', metalness: 0.05, roughness: 0.7 })
export const goldPin = new THREE.MeshStandardMaterial({ color: '#e8c36e', metalness: 0.95, roughness: 0.25 })
export const electrolytic = new THREE.MeshStandardMaterial({ color: '#0d1f4a', metalness: 0.2, roughness: 0.5 })
export const crystalCan = new THREE.MeshStandardMaterial({ color: '#c8ccd2', metalness: 0.95, roughness: 0.28 })
export const switchBtn = new THREE.MeshStandardMaterial({ color: '#6d7480', metalness: 0.2, roughness: 0.6 })
export const whiteDot = new THREE.MeshBasicMaterial({ color: '#ffffff' })

export const ALL_BODY_MATS = [bodyBlack, bodyDark, shieldCan, capBeige, resBody, resTop, endCap, connectorMetal, plasticBlack, goldPin, electrolytic, crystalCan, switchBtn]

export function maskColor(c: MaskColor) { return new THREE.Color(MASK_COLORS[c] ?? MASK_COLORS.black) }
/** copper under solder mask looks like a lighter tint of the mask */
export function pourTint(c: MaskColor) { const col = maskColor(c); const cu = new THREE.Color('#c9975a'); return col.clone().lerp(cu, c === 'white' ? 0.25 : 0.35) }

export function ledColorFrom(value: string, name: string): string {
  const s = (value + ' ' + name).toLowerCase()
  if (s.includes('red')) return '#ff3b3b'
  if (s.includes('green')) return '#4dff6a'
  if (s.includes('blue')) return '#4d7cff'
  if (s.includes('cyan')) return '#3ee7ff'
  if (s.includes('yellow') || s.includes('amber')) return '#ffcf5a'
  if (s.includes('white')) return '#f4f1e6'
  if (s.includes('rgb') || s.includes('ws2812') || s.includes('neopixel')) return '#ff7ad9'
  return '#ffd9a0'
}
