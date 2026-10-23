<#-- Mantém a sincronização de abas fornecida pelo tema nativo do Keycloak. -->
<script type="module">
  <#outputformat "JavaScript">
  import { startSessionPolling, checkAuthSession } from ${(url.resourcesPath + "/js/authChecker.js")?c};
  startSessionPolling(${url.ssoLoginInOtherTabsUrl?c});
  <#if authenticationSession??>
    checkAuthSession(${authenticationSession.authSessionIdHash?c});
  </#if>
  </#outputformat>
</script>
