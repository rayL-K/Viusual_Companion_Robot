export function Manifesto() {
  return (
    <section class="manifesto section" id="vision" aria-labelledby="vision-title">
      <div class="manifesto__index" aria-hidden="true">A / 现在</div>
      <div class="manifesto__copy" data-reveal>
        <h2 id="vision-title">陪伴不是一段生成文本，<br />而是对你此刻状态的连续理解。</h2>
        <p>
          VeyraLux 探索如何把摄像头中的环境语义、语音转写、对话里的指代和可检索记忆放进同一上下文。
          目标不只是回答一句话，而是让角色持续感知、记住并回应一个正在发生的瞬间。
        </p>
      </div>
      <div class="manifesto__aside" data-reveal>
        <p>从“你问，我答”</p>
        <strong>走向持续在场</strong>
      </div>
    </section>
  );
}
