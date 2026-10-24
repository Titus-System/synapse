<#import "template.ftl" as layout>
<@layout.registrationLayout displayMessage=false; section>
  <#if section = "header">
    <#if messageHeader??>${msg(messageHeader)}<#else>${kcSanitize(message.summary)?no_esc}</#if>
  <#elseif section = "form">
    <div id="kc-info-message" role="status">
      <p>${kcSanitize(message.summary)?no_esc}</p>
      <#if requiredActions??>
        <ul><#list requiredActions as action><li>${msg("requiredAction." + action)}</li></#list></ul>
      </#if>
      <#if !skipLink??>
        <#if pageRedirectUri?has_content>
          <a class="synapse-submit" href="${pageRedirectUri}">${msg("backToLogin")}</a>
        <#elseif actionUri?has_content>
          <a class="synapse-submit" href="${actionUri}">${msg("proceedWithAction")}</a>
        <#elseif (client.baseUrl)?has_content>
          <a class="synapse-submit" href="${client.baseUrl}">${msg("backToLogin")}</a>
        </#if>
      </#if>
    </div>
  </#if>
</@layout.registrationLayout>
