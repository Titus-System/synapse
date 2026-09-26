<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>Entrar | Synapse</title>
  <link rel="icon" type="image/x-icon" href="${url.resourcesPath}/img/synapse.ico" />
  <link rel="stylesheet" href="${url.resourcesPath}/css/synapse.css" />
</head>
<body class="synapse-login-page">
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
      <h2 id="titulo-login">Acesse sua conta</h2>
      <p class="synapse-card-description">Ambiente seguro de governança executiva Synapse</p>

      <#if message?has_content>
        <p class="synapse-message synapse-message--${message.type}">${kcSanitize(message.summary)?no_esc}</p>
      </#if>

      <form id="kc-form-login" class="synapse-form" action="${url.loginAction}" method="post">
        <#if !usernameHidden??>
          <label class="synapse-field" for="username">
            <span>E-mail corporativo</span>
            <span class="synapse-input"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="m4.5 7 7.5 5.5L19.5 7"/></svg><input tabindex="1" id="username" name="username" value="${(login.username!'')}" type="text" autocomplete="username" autofocus placeholder="diretoria@corporativo.com.br" aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>" /></span>
          </label>
        </#if>

        <label class="synapse-field" for="password">
          <span class="synapse-field-heading">Senha <#if realm.resetPasswordAllowed><a tabindex="5" href="${url.loginResetCredentialsUrl}">Esqueceu a senha?</a></#if></span>
          <span class="synapse-input"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><rect x="5" y="10" width="14" height="9" rx="2"/><path d="M8.5 10V7a3.5 3.5 0 0 1 7 0v3"/></svg><input tabindex="2" id="password" name="password" type="password" autocomplete="current-password" placeholder="••••••••••" aria-invalid="<#if messagesPerField.existsError('username','password')>true</#if>" /><svg class="synapse-password-eye" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2.5 12s3.4-5 9.5-5 9.5 5 9.5 5-3.4 5-9.5 5-9.5-5-9.5-5Z"/><circle cx="12" cy="12" r="2.2"/></svg></span>
        </label>

        <#if realm.rememberMe && !usernameHidden??>
          <label class="synapse-remember" for="rememberMe"><input tabindex="3" id="rememberMe" name="rememberMe" type="checkbox" <#if login.rememberMe??>checked</#if> /> <span>Lembrar desta estação de trabalho por 30 dias</span></label>
        </#if>

        <button tabindex="4" class="synapse-submit" name="login" id="kc-login" type="submit">Acessar Plataforma <span aria-hidden="true">→</span></button>
      </form>

      <p class="synapse-onboarding">Precisa de autorização? <a href="#">Solicitar onboarding executivo</a></p>
    </section>
  </main>

  <footer class="synapse-footer">
    <span>© 2026 Synapse Enterprise Decisioning. Todos os direitos reservados.</span>
    <nav><a href="#">Termos de uso</a><a href="#">Privacidade &amp; LGPD</a><a href="#">Governança de Dados &amp; IA</a></nav>
  </footer>
</body>
</html>
