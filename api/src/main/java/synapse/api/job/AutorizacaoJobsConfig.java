package synapse.api.job;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
class AutorizacaoJobsConfig implements WebMvcConfigurer {

	private final AutorizacaoJobsInterceptor interceptor;

	AutorizacaoJobsConfig(AutorizacaoJobsInterceptor interceptor) {
		this.interceptor = interceptor;
	}

	@Override
	public void addInterceptors(InterceptorRegistry registry) {
		registry.addInterceptor(this.interceptor).addPathPatterns("/jobs", "/jobs/**");
	}

}
