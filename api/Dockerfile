FROM maven:3.9-eclipse-temurin-21 AS build

ENV MAVEN_OPTS="--add-exports=jdk.compiler/com.sun.tools.javac.api=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.code=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.comp=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.file=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.main=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.model=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.parser=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.processing=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.tree=ALL-UNNAMED \
	--add-exports=jdk.compiler/com.sun.tools.javac.util=ALL-UNNAMED"

WORKDIR /workspace

COPY api/pom.xml ./api/pom.xml
COPY contracts ./contracts
RUN mvn -f api/pom.xml dependency:go-offline

COPY api/src ./api/src
RUN mvn -f api/pom.xml clean package -DskipTests

FROM eclipse-temurin:21-jre

WORKDIR /app

COPY --from=build /workspace/api/target/*.jar app.jar

EXPOSE 8080

ENTRYPOINT ["java", "-jar", "/app/app.jar"]