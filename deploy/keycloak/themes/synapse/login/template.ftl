<#macro registrationLayout bodyClass="" displayInfo=false displayMessage=true displayRequiredFields=false displayWide=false>
<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>${msg("loginTitle", realm.displayName!"Synapse")}</title>
  <link rel="icon" type="image/x-icon" href="${url.resourcesPath}/img/synapse.ico" />
  <script src="${url.resourcesPath}/js/passwordVisibility.js" type="module"></script>
  <#if scripts??><#list scripts as script><script src="${script}"></script></#list></#if>
  <link rel="stylesheet" href="${url.resourcesPath}/css/synapse.css" />
  <#include "synapse-session.ftl">
</head>
<body class="synapse-login-page synapse-account-page">
  <header class="synapse-topbar">
    <a class="synapse-brand" href="#" aria-label="Synapse">
      <img src="${url.resourcesPath}/img/synapse-simbolo.png" alt="" />
      <span>
        <strong>Synapse</strong>
        <small>Decision architecture</small>
      </span>
    </a>
    <span class="synapse-status"><i></i> By Titus System</span>
  </header>

  <main class="synapse-layout">
    <section class="synapse-hero" aria-labelledby="titulo-apresentacao">
      <p class="synapse-pill"><span aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13.1 2 4.3 13h6.2L9.8 22l9.9-12h-6.2L13.1 2Z"/></svg></span> Governança Cognitiva &amp; Execução de Regras</p>
      <h1 id="titulo-apresentacao">Sua voz dita as regras.<br><em>A IA garante os resultados.</em></h1>
      <p class="synapse-description">Converta diretrizes executivas estratégicas em lógica de negócio determinística. Simule impactos de risco e orçamentários antes do deploy em produção com auditoria matemática em tempo real.</p>

      <ul class="synapse-trust">
        <li><span>◇</span> SOC2 Type II Certificado</li>
        <li><span>♧</span> Criptografia mTLS Ponta a Ponta</li>
        <li><span>●</span> Isolamento Multi-Tenant Dedicado</li>
      </ul>
    </section>

    <section class="synapse-card" aria-labelledby="titulo-login">
      <span class="synapse-card-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><rect x="5" y="10" width="14" height="9" rx="2"/><path d="M8.5 10V7a3.5 3.5 0 0 1 7 0v3"/><path d="M12 13.5v2.5"/></svg></span>
      <h2 id="titulo-login"><#nested "header"></h2>
      <#if displayRequiredFields><p class="synapse-help">${msg("requiredFields")}</p></#if>
      <#if displayRequiredFields && passwordPolicies?? && (passwordPolicies.length!0) gt 0>
        <p class="synapse-help">${msg("synapsePasswordHint", passwordPolicies.length)}</p>
      </#if>
      <#if displayMessage && message?has_content>
        <div role="alert" class="synapse-message synapse-message--${message.type}">${kcSanitize(message.summary)?no_esc}</div>
      </#if>
      <#nested "form">
      <#if displayInfo><div class="synapse-help"><#nested "info"></div></#if>
    </section>
  </main>

  <footer class="synapse-footer">
    <span>© 2026 Synapse Enterprise Decisioning. Todos os direitos reservados.</span>
    <nav><a href="#">Termos de uso</a><a href="#">Privacidade &amp; LGPD</a><a href="#">Governança de Dados &amp; IA</a></nav>
  </footer>
</body>
</html>

</#macro>
