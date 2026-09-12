import React, { useEffect, useRef } from 'react'
import * as THREE from 'three'

interface ThreeRadarCanvasProps {
  colorHex?: string
  className?: string
}

// 4 Well-spaced, high-value featured targets (2 Talent, 2 Customer)
const FEATURED_SIGNALS = [
  {
    id: 't1',
    type: 'talent' as const,
    title: 'Lead AI Engineer',
    subtitle: '8+ năm kn • Xử lý LLM, RAG & MLOps',
    score: '98% Khớp',
    angle: 0.6,
    distance: 4.6,
    elevation: 0.4,
  },
  {
    id: 'c1',
    type: 'customer' as const,
    title: 'Tập đoàn Công nghệ FDI',
    subtitle: 'Doanh thu 500B+ • Nhu cầu Tín dụng & L/C',
    score: '95% Tiềm năng',
    angle: 2.1,
    distance: 6.2,
    elevation: 0.6,
  },
  {
    id: 't2',
    type: 'talent' as const,
    title: 'Giám đốc Trung tâm Khách hàng',
    subtitle: 'MSB Priority Banking • 10+ năm quản lý',
    score: '96% Khớp',
    angle: 3.7,
    distance: 5.5,
    elevation: 0.5,
  },
  {
    id: 'c2',
    type: 'customer' as const,
    title: 'Chuỗi Bán lẻ Tiêu dùng',
    subtitle: 'Mở rộng 50 POS • Nhu cầu Vốn lưu động',
    score: '97% Tiềm năng',
    angle: 5.2,
    distance: 6.8,
    elevation: 0.7,
  },
]

export const ThreeRadarCanvas: React.FC<ThreeRadarCanvasProps> = ({
  colorHex = '#FF8A33',
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({})

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    let animationFrameId: number
    let renderer: THREE.WebGLRenderer | null = null

    try {
      // 1. Scene & Camera Setup - Compact sizing for 14" screens
      const scene = new THREE.Scene()
      scene.fog = new THREE.FogExp2(0x060913, 0.026)

      const camera = new THREE.PerspectiveCamera(
        40,
        container.clientWidth / container.clientHeight,
        0.1,
        120
      )
      camera.position.set(0, 16, 22)
      camera.lookAt(0, -0.2, 0)

      // 2. High-performance WebGL Renderer
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: 'high-performance',
      })
      renderer.setSize(container.clientWidth, container.clientHeight)
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      renderer.toneMapping = THREE.ACESFilmicToneMapping
      renderer.toneMappingExposure = 1.15
      container.appendChild(renderer.domElement)

      // Dynamic Color Scheme mapped from /settings (colorHex)
      const primaryTheme = new THREE.Color(colorHex)
      const hsl = { h: 0, s: 0, l: 0 }
      primaryTheme.getHSL(hsl)

      const secondaryTheme = new THREE.Color().setHSL(
        (hsl.h + 0.07) % 1.0,
        Math.min(1.0, Math.max(0.65, hsl.s * 1.1)),
        Math.min(0.85, Math.max(0.48, hsl.l * 1.15 + 0.05))
      )
      const customerCyan = new THREE.Color('#06B6D4')

      // 3. Dynamic Cursor Lighting (Soft ambient glow matching setting theme)
      const mouseLight = new THREE.PointLight(primaryTheme, 2.2, 26)
      mouseLight.position.set(0, 8, 5)
      scene.add(mouseLight)

      const centerCoreLight = new THREE.PointLight(secondaryTheme, 2.8, 10)
      centerCoreLight.position.set(0, 0.3, 0)
      scene.add(centerCoreLight)

      // 4. Main Hologram Radar Dish Group
      const mainRadarGroup = new THREE.Group()
      scene.add(mainRadarGroup)

      // Concentric Glowing Rings
      const ringRadii = [1.6, 3.5, 5.6, 7.8, 9.8]
      ringRadii.forEach((radius, idx) => {
        const segments = 120
        const circleGeo = new THREE.BufferGeometry()
        const positions = new Float32Array((segments + 1) * 3)

        for (let i = 0; i <= segments; i++) {
          const theta = (i / segments) * Math.PI * 2
          positions[i * 3] = Math.cos(theta) * radius
          positions[i * 3 + 1] = 0
          positions[i * 3 + 2] = Math.sin(theta) * radius
        }

        circleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))

        const isOuter = idx === ringRadii.length - 1
        const circleMat = new THREE.LineBasicMaterial({
          color: isOuter ? primaryTheme : primaryTheme,
          transparent: true,
          opacity: isOuter ? 0.75 : 0.16 + idx * 0.08,
          linewidth: isOuter ? 2 : 1,
        })

        const ringLine = new THREE.Line(circleGeo, circleMat)
        mainRadarGroup.add(ringLine)
      })

      // Outer Ring with Compass Tick Marks
      const ticksGroup = new THREE.Group()
      mainRadarGroup.add(ticksGroup)

      const tickCount = 56
      const tickRadius = 9.8
      const tickPositions: number[] = []

      for (let i = 0; i < tickCount; i++) {
        const theta = (i / tickCount) * Math.PI * 2
        const isMajor = i % 7 === 0
        const len = isMajor ? 0.4 : 0.18

        tickPositions.push(
          Math.cos(theta) * tickRadius, 0, Math.sin(theta) * tickRadius,
          Math.cos(theta) * (tickRadius + len), 0, Math.sin(theta) * (tickRadius + len)
        )
      }

      const ticksGeo = new THREE.BufferGeometry()
      ticksGeo.setAttribute('position', new THREE.Float32BufferAttribute(tickPositions, 3))
      const ticksMat = new THREE.LineBasicMaterial({
        color: secondaryTheme,
        transparent: true,
        opacity: 0.5,
      })
      const ticksMesh = new THREE.LineSegments(ticksGeo, ticksMat)
      ticksGroup.add(ticksMesh)

      // Friendly Coordinate Grid Crosshairs
      const gridLinesGeo = new THREE.BufferGeometry()
      const gridPositions = new Float32Array([
        -10.5, 0, 0, 10.5, 0, 0,
        0, 0, -10.5, 0, 0, 10.5,
        -7.5, 0, -7.5, 7.5, 0, 7.5,
        -7.5, 0, 7.5, 7.5, 0, -7.5,
      ])
      gridLinesGeo.setAttribute('position', new THREE.BufferAttribute(gridPositions, 3))
      const gridLinesMat = new THREE.LineBasicMaterial({
        color: primaryTheme,
        transparent: true,
        opacity: 0.16,
      })
      const gridLines = new THREE.LineSegments(gridLinesGeo, gridLinesMat)
      mainRadarGroup.add(gridLines)

      // Center Flat Core Disc
      const centerDiscGeo = new THREE.CircleGeometry(0.55, 32)
      const centerDiscMat = new THREE.MeshBasicMaterial({
        color: primaryTheme,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.8,
      })
      const centerDisc = new THREE.Mesh(centerDiscGeo, centerDiscMat)
      centerDisc.rotation.x = Math.PI / 2
      centerDisc.position.y = 0.01
      mainRadarGroup.add(centerDisc)

      const centerHaloGeo = new THREE.RingGeometry(0.7, 0.9, 32)
      const centerHaloMat = new THREE.MeshBasicMaterial({
        color: secondaryTheme,
        side: THREE.DoubleSide,
        transparent: true,
        opacity: 0.45,
        blending: THREE.AdditiveBlending,
      })
      const centerHalo = new THREE.Mesh(centerHaloGeo, centerHaloMat)
      centerHalo.rotation.x = Math.PI / 2
      centerHalo.position.y = 0.01
      mainRadarGroup.add(centerHalo)

      // 5. Sweeping Radar Beam (Soft fan + Laser line)
      const sweepGroup = new THREE.Group()
      mainRadarGroup.add(sweepGroup)

      const sweepAngle = Math.PI / 2.8 // ~64 degrees
      const sweepSegments = 40
      const sweepGeo = new THREE.BufferGeometry()
      const sweepPositions = new Float32Array((sweepSegments + 2) * 3)
      const sweepColors = new Float32Array((sweepSegments + 2) * 4)

      sweepPositions[0] = 0
      sweepPositions[1] = 0.02
      sweepPositions[2] = 0
      sweepColors[0] = primaryTheme.r
      sweepColors[1] = primaryTheme.g
      sweepColors[2] = primaryTheme.b
      sweepColors[3] = 0.8

      for (let i = 0; i <= sweepSegments; i++) {
        const fraction = i / sweepSegments
        const theta = -fraction * sweepAngle
        const r = 9.9

        sweepPositions[(i + 1) * 3] = Math.cos(theta) * r
        sweepPositions[(i + 1) * 3 + 1] = 0.02
        sweepPositions[(i + 1) * 3 + 2] = Math.sin(theta) * r

        const alpha = Math.pow(1 - fraction, 2.0) * 0.48
        sweepColors[(i + 1) * 4] = primaryTheme.r
        sweepColors[(i + 1) * 4 + 1] = primaryTheme.g
        sweepColors[(i + 1) * 4 + 2] = primaryTheme.b
        sweepColors[(i + 1) * 4 + 3] = alpha
      }

      const indices: number[] = []
      for (let i = 1; i <= sweepSegments; i++) {
        indices.push(0, i, i + 1)
      }

      sweepGeo.setAttribute('position', new THREE.BufferAttribute(sweepPositions, 3))
      sweepGeo.setAttribute('color', new THREE.BufferAttribute(sweepColors, 4))
      sweepGeo.setIndex(indices)

      const sweepMat = new THREE.MeshBasicMaterial({
        vertexColors: true,
        transparent: true,
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending,
      })
      const sweepMesh = new THREE.Mesh(sweepGeo, sweepMat)
      sweepGroup.add(sweepMesh)

      const laserGeo = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(0, 0.03, 0),
        new THREE.Vector3(9.9, 0.03, 0),
      ])
      const laserMat = new THREE.LineBasicMaterial({
        color: 0xffffff,
        transparent: true,
        opacity: 0.95,
        linewidth: 2,
      })
      const laserLine = new THREE.Line(laserGeo, laserMat)
      sweepGroup.add(laserLine)

      // 6. Target Nodes
      const targetMeshes: Array<{
        target: (typeof FEATURED_SIGNALS)[0]
        mesh: THREE.Mesh
        auraMesh: THREE.Mesh
        stemLine: THREE.Line
        intensity: number
        pos: THREE.Vector3
      }> = []

      FEATURED_SIGNALS.forEach((signal) => {
        const isTalent = signal.type === 'talent'
        const nodeColor = isTalent ? primaryTheme : customerCyan
        const pos = new THREE.Vector3(
          Math.cos(signal.angle) * signal.distance,
          signal.elevation,
          Math.sin(signal.angle) * signal.distance
        )

        // Core Sphere
        const nodeGeo = new THREE.SphereGeometry(0.16, 16, 16)
        const nodeMat = new THREE.MeshBasicMaterial({
          color: nodeColor,
          transparent: true,
          opacity: 0.35,
        })
        const nodeMesh = new THREE.Mesh(nodeGeo, nodeMat)
        nodeMesh.position.copy(pos)
        mainRadarGroup.add(nodeMesh)

        // Pulsing Ring
        const auraGeo = new THREE.RingGeometry(0.16, 0.45, 24)
        const auraMat = new THREE.MeshBasicMaterial({
          color: nodeColor,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        })
        const auraMesh = new THREE.Mesh(auraGeo, auraMat)
        auraMesh.rotation.x = Math.PI / 2
        auraMesh.position.copy(pos)
        mainRadarGroup.add(auraMesh)

        // Stem Line
        const stemGeo = new THREE.BufferGeometry().setFromPoints([
          new THREE.Vector3(pos.x, 0, pos.z),
          pos,
        ])
        const stemMat = new THREE.LineBasicMaterial({
          color: nodeColor,
          transparent: true,
          opacity: 0.2,
        })
        const stemLine = new THREE.Line(stemGeo, stemMat)
        mainRadarGroup.add(stemLine)

        targetMeshes.push({
          target: signal,
          mesh: nodeMesh,
          auraMesh,
          stemLine,
          intensity: 0,
          pos,
        })
      })

      // 7. Dynamic Constellation Vector Links
      const maxLinks = 10
      const linkPositions = new Float32Array(maxLinks * 2 * 3)
      const linkGeo = new THREE.BufferGeometry()
      linkGeo.setAttribute('position', new THREE.BufferAttribute(linkPositions, 3))
      const linkMat = new THREE.LineBasicMaterial({
        color: secondaryTheme,
        transparent: true,
        opacity: 0.4,
        blending: THREE.AdditiveBlending,
      })
      const linkMesh = new THREE.LineSegments(linkGeo, linkMat)
      mainRadarGroup.add(linkMesh)

      // 8. Expanding Sonar Echo Ripples
      const rippleCount = 3
      const ripples: Array<{ mesh: THREE.Mesh; scale: number; speed: number }> = []

      for (let i = 0; i < rippleCount; i++) {
        const ripGeo = new THREE.RingGeometry(0.2, 0.32, 64)
        const ripMat = new THREE.MeshBasicMaterial({
          color: primaryTheme,
          side: THREE.DoubleSide,
          transparent: true,
          opacity: 0.45,
          depthWrite: false,
          blending: THREE.AdditiveBlending,
        })
        const ripMesh = new THREE.Mesh(ripGeo, ripMat)
        ripMesh.rotation.x = Math.PI / 2
        mainRadarGroup.add(ripMesh)
        ripples.push({ mesh: ripMesh, scale: (i / rippleCount) * 9.8, speed: 0.025 + i * 0.005 })
      }

      // 9. Ambient Particle Field
      const particleCount = 150
      const particleGeo = new THREE.BufferGeometry()
      const particlePos = new Float32Array(particleCount * 3)

      for (let i = 0; i < particleCount; i++) {
        particlePos[i * 3] = (Math.random() - 0.5) * 26
        particlePos[i * 3 + 1] = Math.random() * 6 - 1
        particlePos[i * 3 + 2] = (Math.random() - 0.5) * 26
      }
      particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePos, 3))
      const particleMat = new THREE.PointsMaterial({
        size: 0.08,
        color: secondaryTheme,
        transparent: true,
        opacity: 0.35,
        blending: THREE.AdditiveBlending,
      })
      const particles = new THREE.Points(particleGeo, particleMat)
      scene.add(particles)

      // 10. Mouse Parallax
      let mouseX = 0
      let mouseY = 0
      let targetCameraX = 0
      let targetCameraY = 16
      let targetCameraZ = 22

      const handlePointerMove = (e: MouseEvent) => {
        const rect = container.getBoundingClientRect()
        const nx = ((e.clientX - rect.left) / rect.width) * 2 - 1
        const ny = -(((e.clientY - rect.top) / rect.height) * 2 - 1)
        mouseX = nx
        mouseY = ny

        mouseLight.position.x = nx * 8
        mouseLight.position.z = 5 - ny * 4
      }

      window.addEventListener('pointermove', handlePointerMove)

      // 11. Resize Observer
      const handleResize = () => {
        if (!container || !renderer) return
        const width = container.clientWidth
        const height = container.clientHeight
        camera.aspect = width / height
        camera.updateProjectionMatrix()
        renderer.setSize(width, height)
      }

      window.addEventListener('resize', handleResize)

      // 12. Master 60FPS Render Loop
      const clock = new THREE.Clock()
      const tempVec = new THREE.Vector3()

      const animate = () => {
        animationFrameId = requestAnimationFrame(animate)

        const delta = Math.min(clock.getDelta(), 0.1)
        const elapsedTime = clock.getElapsedTime()

        // Steady gentle sweep rotation
        sweepGroup.rotation.y -= delta * 1.1
        const currentBeamAngle = -sweepGroup.rotation.y % (Math.PI * 2)

        // Rotate Outer Ticks & Center Halo
        ticksGroup.rotation.y += delta * 0.05
        centerHalo.rotation.z -= delta * 0.25

        // Animate Ripples
        ripples.forEach((rip) => {
          rip.scale += rip.speed
          if (rip.scale > 9.8) {
            rip.scale = 0.2
          }
          rip.mesh.scale.set(rip.scale, rip.scale, 1)
          const ripMat = rip.mesh.material as THREE.MeshBasicMaterial
          ripMat.opacity = (1 - rip.scale / 9.8) * 0.45
        })

        // Update Target Nodes & Project to 2D Screen Overlay Cards
        const activeBlips: typeof targetMeshes = []

        const width = container.clientWidth
        const height = container.clientHeight

        targetMeshes.forEach(({ target, mesh, auraMesh, stemLine }, idx) => {
          let normalizedAngle = target.angle % (Math.PI * 2)
          if (normalizedAngle < 0) normalizedAngle += Math.PI * 2

          let angleDiff = Math.abs(currentBeamAngle - normalizedAngle)
          if (angleDiff > Math.PI) angleDiff = Math.PI * 2 - angleDiff

          let intensity = targetMeshes[idx].intensity

          // When the beam hits, set full intensity
          if (angleDiff < 0.22) {
            intensity = 1.0
          } else {
            // Slower decay rate (0.18) so popup stays visible for ~4-5s for easy reading!
            intensity = Math.max(0.18, intensity - delta * 0.18)
          }
          targetMeshes[idx].intensity = intensity

          const mat = mesh.material as THREE.MeshBasicMaterial
          mat.opacity = 0.3 + intensity * 0.7

          const pulseMat = auraMesh.material as THREE.MeshBasicMaterial
          pulseMat.opacity = Math.max(0, (intensity - 0.2) * 0.8)
          const scale = 1 + (1 - intensity) * 1.8
          auraMesh.scale.set(scale, scale, scale)

          // Floating bob
          const floatY = target.elevation + Math.sin(elapsedTime * 2.0 + target.distance) * 0.08
          mesh.position.y = floatY
          auraMesh.position.y = floatY

          const stemMat = stemLine.material as THREE.LineBasicMaterial
          stemMat.opacity = 0.1 + intensity * 0.35

          if (intensity > 0.3) {
            activeBlips.push(targetMeshes[idx])
          }

          // Calculate 2D Screen Projection with safe containment bounds
          tempVec.copy(mesh.position)
          tempVec.project(camera)

          const rawX = ((tempVec.x + 1) / 2) * width
          const rawY = ((-tempVec.y + 1) / 2) * height

          // Safe clamping so cards never clip off the screen edge
          const marginX = 120
          const marginY = 60
          const screenX = Math.max(marginX, Math.min(width - marginX, rawX))
          const screenY = Math.max(marginY, Math.min(height - marginY, rawY))

          // Direct DOM style update for 60fps performance without React re-renders
          const cardEl = cardRefs.current[target.id]
          if (cardEl) {
            const isVisible = tempVec.z < 1 && intensity > 0.32
            if (isVisible) {
              cardEl.style.opacity = `${Math.min(1, (intensity - 0.2) * 1.4)}`
              cardEl.style.transform = `translate3d(${screenX}px, ${screenY}px, 0) translate(-50%, -120%)`
            } else {
              cardEl.style.opacity = '0'
            }
          }
        })

        // Build Dynamic Constellation Links
        let linkIdx = 0
        const linkPosAttr = linkGeo.attributes.position as THREE.BufferAttribute
        const linkArray = linkPosAttr.array as Float32Array

        for (let i = 0; i < activeBlips.length && linkIdx < maxLinks; i++) {
          for (let j = i + 1; j < activeBlips.length && linkIdx < maxLinks; j++) {
            const p1 = activeBlips[i].mesh.position
            const p2 = activeBlips[j].mesh.position
            if (p1.distanceTo(p2) < 7.0) {
              linkArray[linkIdx * 6] = p1.x
              linkArray[linkIdx * 6 + 1] = p1.y
              linkArray[linkIdx * 6 + 2] = p1.z

              linkArray[linkIdx * 6 + 3] = p2.x
              linkArray[linkIdx * 6 + 4] = p2.y
              linkArray[linkIdx * 6 + 5] = p2.z

              linkIdx++
            }
          }
        }

        for (let i = linkIdx * 6; i < maxLinks * 6; i++) {
          linkArray[i] = 0
        }
        linkPosAttr.needsUpdate = true

        // Smooth Camera Parallax Tilt
        targetCameraX = mouseX * 2.2
        targetCameraY = 16 + mouseY * 1.8
        targetCameraZ = 22 - Math.abs(mouseX) * 1.0
        camera.position.x += (targetCameraX - camera.position.x) * 0.045
        camera.position.y += (targetCameraY - camera.position.y) * 0.045
        camera.position.z += (targetCameraZ - camera.position.z) * 0.045
        camera.lookAt(0, -0.2, 0)

        // Ambient Particle Rotation
        particles.rotation.y = elapsedTime * 0.018

        renderer!.render(scene, camera)
      }

      animate()

      // Cleanup
      return () => {
        window.removeEventListener('pointermove', handlePointerMove)
        window.removeEventListener('resize', handleResize)
        cancelAnimationFrame(animationFrameId)

        if (renderer && renderer.domElement && container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement)
          renderer.dispose()
        }
      }
    } catch (err) {
      console.warn('Three.js Radar initialization fallback:', err)
    }
  }, [colorHex])

  return (
    <div
      ref={containerRef}
      className={`three-radar-canvas-wrap ${className}`}
      style={
        {
          position: 'absolute',
          top: 0,
          left: 0,
          width: '100%',
          height: '100%',
          overflow: 'hidden',
          pointerEvents: 'auto',
          '--radar-theme-color': colorHex,
        } as React.CSSProperties
      }
    >
      {/* 2D Holographic Target Overlay Cards */}
      <div className="radar-target-cards-container" style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
        {FEATURED_SIGNALS.map((signal) => {
          const isTalent = signal.type === 'talent'
          return (
            <div
              key={signal.id}
              ref={(el) => { cardRefs.current[signal.id] = el }}
              className={`radar-target-card ${isTalent ? 'talent' : 'customer'}`}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                opacity: 0,
                transform: 'translate(-50%, -120%)',
                willChange: 'transform, opacity',
                transition: 'opacity 0.25s ease',
              }}
            >
              <div className="radar-target-badge">
                <span className="radar-target-dot" />
                <span>{isTalent ? '🎯 Ứng Viên Tiềm Năng' : '💼 Khách Hàng Tiềm Năng'}</span>
                <span className="radar-target-score">{signal.score}</span>
              </div>
              <div className="radar-target-title">{signal.title}</div>
              <div className="radar-target-subtitle">{signal.subtitle}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
export default ThreeRadarCanvas
