---
title: 'QGIS pypopRF Plugin: A tool for the construction of gridded population distribution maps'
tags:
  - Python
  - QGIS
  - GIS
  - population mapping
  - population data
  - random forest
  - machine learning
authors:
  - name: Tom McKeen
    orcid: 0000-0003-4499-7319
    corresponding: true
    affiliation: "1"
  - name: Rhorom Priyatikanto
    orcid: 0000-0003-1203-2651
    affiliation: "1"
  - name: Borys Nosatiuk
    orcid:
    affiliation: "1"
  - name: Wenbin Zhang
    orcid: 0000-0002-9295-1019
    affiliation: "1"
  - name: Elena Vataga
    affiliation: "1"
  - name: Natalia Tejedor-Garavito
    orcid: 0000-0002-1140-6263
    affiliation: "1"
  - name: Andrew J. Tatem
    orcid: 0000-0002-7270-941X
    affiliation: "1"
  - name: Maksym Bondarenko
    orcid: 0000-0003-4958-6551
    affiliation: "1"
affiliations:
 - name: WorldPop, School of Geography and Environmental Science, University of Southampton, Southampton SO17 1BJ, UK
   index: 1
   ror: 01ryk1543
date: 16 December 2025
bibliography: paper.bib
---

# Summary

Accurate data on the spatial distribution of population is an essential source of information to a wide range of environmental, health and sustainable developmental applications. Considerable work has been undertaken to develop modelled gridded datasets that accurately capture population distributions at subnational scales. However, generating these datasets demands specialised expertise in statistical modelling and computational programming. To overcome these challenges, the Spatial Data Infrastructure (SDI) Team at WorldPop have developed the QGIS pypopRF Plugin, a high-resolution population mapping tool that uses machine learning and dasymetric techniques within open-source GIS software [@QGIS_2025]. Built on the pypopRF Python package [@Priyatikanto_2025], the Plugin transforms input data into detailed gridded population distribution maps using a random forest (RF) dasymetric modelling approach [@Stevens_2015], combining census data, building information and spatial constraints within a graphical interface that enables non-technical users to implement top-down population disaggregation methods [@Wardrop_2018] without programming expertise. This paper aims to describe the core functionality and features of the QGIS pypopRF Plugin, and how the plugin can be leveraged to create high-resolution gridded population data.

# Statement of need

Globally, population dynamics display considerable variation across local-regional scales due to the interface of a series of phenomena. Notable amongst these phenomena are demographic trends [@OECD_2024], urbanisation [@Sun_2020], and migration patterns [@Qiao_2024] which shape human population distribution and change in distinct ways across countries and regions. In this setting, subnational population datasets are essential to capturing these dynamics and therefore a swathe of applications, including public health strategy, disaster risk management, urban planning and resource allocation [@Maneepong_2025; @Wardrop_2018]. 

However, generating gridded population typically requires expertise in statistical methods and programming skills [@Leyk_2019; @Tatem_2007]. In-fact, tools that precede this plugin, pypopRF [@Priyatikanto_2025] and popRF for R [@Bondarenko_2021], are primarily operable at a command-line or scripting level, thereby limiting the accessibility to a wider community. Therefore, open-source and replicable tools for population modelling are crucial to bridging the gap between data curators and data users [@Mobasheri_2020].

The QGIS pypopRF plugin seeks to address these challenges by providing an integrated tool accessible to GIS practitioners, analysts and educators/students. By embedding the pypopRF package [@Priyatikanto_2025] directly into QGIS, the plugin facilitates a consistent, reproducible workflow for gridded population data creation with detailed logging options within a single environment. This enhances the transparency of methods, enabling users to document and share model configurations as well as outputs.

# State of the field

There are several existing open-source tools and packages to support population disaggregation and dasymetric mapping through the implementation of RF methods. These include WorldPop’s R-based popRF package [@Bondarenko_2021] and the Python-based pypopRF package [@Priyatikanto_2025]. Whilst both popRF and pypopRF offer robust and reproducible implementations of RF-based population modelling, they are accessed via scripting or command-line workflows. This limits their accessibility to users without programming expertise, despite strong demand from GIS practitioners, analysts and students working in desktop GIS environments.
The QGIS pypopRF Plugin addresses this gap by embedding the population modelling workflow directly within QGIS, a widely adopted open-source GIS platform. Rather than duplicating modelling logic, the plugin builds upon the validated pypopRF package [@Priyatikanto_2025] while contributing a graphical interface, workflow orchestration, logging, and data management layer tailored to applied geospatial analysis. This “build-on” approach prioritises accessibility and integration with existing GIS workflows, enabling a broader community to apply advanced population modelling methods without the need to write code.

# Software design
Architecturally, the plugin is built for QGIS [@QGIS_2025] using a modular PyQt tabbed interface (including sections for project setup, inputs, settings and a console) \autoref{fig:user_interface}, with core functionality provided by the pypopRF Python package [@Priyatikanto_2025]. This implements the top-down dasymetric disaggregation method including census normalisation, covariate stacking into arrays, RF prediction and optional spatial or age-sex constraints. Memory-efficient raster processing is achieved through chunking, avoiding full in-memory loads for larger covariate datasets.

![User interface of the pypopRF Plugin for QGIS.\label{fig:user_interface}](figure1.png)

The RF model [@Stevens_2015] is trained at administrative unit level using user-supplied covariate rasters; these are geospatial variables correlated with population distribution such as building footprints, infrastructure or elevation. A population density weighting layer is generated at the target resolution and applied to disaggregate census counts into grid cells defined by a mastergrid raster. Prediction areas can be refined using an optional mask (e.g. inland water bodies) to exclude uninhabited areas, or a constraint layer (e.g. human settlement footprint) to restrict population estimates to built areas. The analysis produces GeoTIFF outputs at multiple levels \autoref{fig:outputs}: normalised census-adjusted values, unconstrained population distribution, and where a constraint layer is provided, constrained population distribution. Where age-sex data are supplied, additional disaggregated outputs are generated alongside diagnostics including processing logs, feature scalers and covariate importance scores, enabling users to assess the relative influence of predictor variables.
Key design trade-offs were considered between computational efficiency, model accuracy and geospatial usability. The plugin leverages rasterio [@Gillies_2019] for raster input and output operations, ensuring efficient handling of geospatial covariates. For data manipulation, pandas [@Pandas_2020] and its spatial extension geopandas [@Jordahl_2020] enable analysis of vector data associated with the raster information. To optimise performance, joblib [@Joblib_2025] is integrated for parallel processing, significantly speeding up computation by utilising multi-core processors. The foundational machine learning capabilities are provided by scikit-learn [@Pedregosa_2011], supporting the construction and application of the RF model. This design is particularly relevant for research such as WorldPop's settlement modelling, in which precise gridded population estimates (~100m resolution) are used for tracking internally displaced populations and disaster response. The plugin is designed to be interpretable to aid peer review and transparency, whilst being scalable for iterative workflows in QGIS pipelines, promoting reproducible research in low-resource settings.

![Output rasters from the model. (a) normalised census adjusted values, (b), unconstrained population distribution (default), and (c) constrained population distribution (when a constraint layer is provided).\label{fig:outputs}](figure2.png)


# Research impact statement

The QGIS pypopRF Plugin has been developed by the WorldPop SDI team to support the production of high-resolution population datasets across low- and middle-income country contexts. It directly supports WorldPop’s mission to enable transparent, reproducible, and locally adaptable population mapping, complementing existing global datasets with a tool for country-specific or subnational analysis.

The plugin is actively used within WorldPop workflows for method development and has also been applied in capacity-building settings to introduce population modelling concepts to GIS practitioners without programming experience. The continued use in operations and capacity building provides ongoing user feedback, supporting sustained development and ensuring the tool remains aligned with applied research needs. Given the widespread adoption of QGIS, the plugin is well positioned for broader uptake in research, training, and collaborative settings where accessible and reproducible methods are needed.

# AI usage disclosure

No generative AI tools were used in the development of this software, the writing of this manuscript, or the preparation of supporting materials.

# Acknowledgements

This work was supported by funds from the Gates Foundation (INV-045237 and INV-088965) and Wellcome Trust (308679/Z/23/Z). This work forms part of the outputs of WorldPop (www.worldpop.org). The funders had no role in study design, data collection and analysis, decision to publish, or preparation of the manuscript.

# References
