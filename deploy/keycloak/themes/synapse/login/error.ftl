<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
  <#if section = "header">
    ${msg("errorTitle")}
  <#elseif section = "form">
    <div id="kc-error-message" role="alert">
      <p>${kcSanitize(message.summary)?no_esc}</p>
      <p>${msg("synapseRestartInstruction")}</p>
    </div>
    <#if client?? && client.baseUrl?has_content>
      <p><a id="backToApplication" href="${client.baseUrl}">${msg("backToApplication")}</a></p>
    <#else>
      <p><a href="${url.loginRestartFlowUrl}">${msg("backToLogin")}</a></p>
    </#if>
  </#if>
</@layout.registrationLayout>
