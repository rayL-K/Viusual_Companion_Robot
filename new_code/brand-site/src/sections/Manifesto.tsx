export function Manifesto() {
  return (
    <section class="manifesto section" id="vision" aria-labelledby="vision-title">
      <div class="manifesto__index" aria-hidden="true" data-motion-layer="presence-spine" data-motion-behavior="scrub" data-motion-scope="manifesto"><span>持续在场</span><i /></div>
      <div class="manifesto__copy" data-motion="manifesto-copy" data-motion-layer="presence-copy" data-motion-behavior="scrub" data-motion-scope="manifesto">
        <h2 id="vision-title">陪伴不是一段生成文本，<br />而是对你此刻状态的连续理解。</h2>
        <p>
          VeyraLux 探索如何把摄像头中的环境语义、语音转写、对话里的指代和可检索记忆放进同一上下文。
          目标不只是回答一句话，而是让角色持续感知、记住并回应一个正在发生的瞬间。
        </p>
      </div>
      <ol class="presence-stream" aria-label="连续陪伴上下文" data-motion-layer="presence-stream" data-motion-behavior="scrub" data-motion-scope="manifesto">
        <li><span>01</span><strong>看见环境</strong><small>画面语义持续更新</small></li>
        <li><span>02</span><strong>听懂此刻</strong><small>语音和指代进入上下文</small></li>
        <li><span>03</span><strong>连接过往</strong><small>有界记忆参与理解</small></li>
        <li><span>04</span><strong>同步回应</strong><small>语言、声音与动作一起抵达</small></li>
      </ol>
    </section>
  );
}
