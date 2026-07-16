const stages = [
  { name: "感知", detail: "目标：让画面、声音与文字汇入同一端侧链路" },
  { name: "理解", detail: "目标：融合人物、情绪、动作与环境语义" },
  { name: "记忆", detail: "目标：把当下与可检索过往组成有界上下文" },
  { name: "回应", detail: "目标：协同生成语言、语音与角色意图" },
  { name: "呈现", detail: "目标：让口型、表情与声音按同一代际抵达" },
];

export function Pipeline() {
  return (
    <section class="pipeline section" id="pipeline" aria-labelledby="pipeline-title">
      <div class="pipeline__scene">
        <header class="section-heading" data-motion="pipeline-heading">
          <p>一条回应，五次接力</p>
          <h2 id="pipeline-title">把“等待感”拆到每一个环节。</h2>
          <span>语义先后相依，计算可以并行准备。Anima v0.0.1 让模块保持独立，并以可取消的事件流衔接数据。</span>
        </header>

        <div class="signal-flow" data-motion-layer="pipeline-flow" data-motion-behavior="scrub" data-motion-scope="pipeline">
          <div class="signal-flow__rail" aria-hidden="true"><span class="signal-flow__progress" /></div>
          <ol class="signal-flow__list" aria-label="多模态交互处理流程">
            {stages.map((stage, index) => (
              <li class="signal-flow__stage" data-stage={index}>
                <div class="signal-flow__node"><span>{String(index + 1).padStart(2, "0")}</span></div>
                <div><h3>{stage.name}</h3><p>{stage.detail}</p></div>
              </li>
            ))}
          </ol>
        </div>

        <div class="pipeline__statement" data-motion="pipeline-statement">
          <span>不是把云端能力简单搬上开发板。</span>
          <strong>而是围绕端侧约束重新设计对话链路。</strong>
        </div>
      </div>
    </section>
  );
}
