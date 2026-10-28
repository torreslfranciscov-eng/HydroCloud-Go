FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY . .
RUN dotnet publish HydroCloud.Admin.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
RUN mkdir -p /app/App_Data /tmp/dpkeys && chown -R 1000:1000 /app /tmp/dpkeys
ENV ASPNETCORE_ENVIRONMENT=Production
USER 1000
EXPOSE 8080
ENTRYPOINT ["sh", "-c", "exec dotnet HydroCloud.Admin.dll --urls http://0.0.0.0:${PORT:-8080}"]
