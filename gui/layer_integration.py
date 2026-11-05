"""Native QGIS layers and display-only styles; never rewrite scientific data."""
import math
from pathlib import Path

from qgis.PyQt.QtCore import QMetaType, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QInputDialog
from qgis.core import (Qgis, QgsProject, QgsProviderRegistry, QgsRasterLayer, QgsVectorLayer,
    QgsRasterShader, QgsColorRampShader, QgsSingleBandPseudoColorRenderer,
    QgsCoordinateReferenceSystem, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsLayerTreeGroup)


def local_layer_source(layer, kind=None):
    """Reject memory, remote and virtual sources; retain an explicit OGR layer."""
    raster = isinstance(layer, QgsRasterLayer)
    vector = isinstance(layer, QgsVectorLayer)
    if not layer.isValid() or (kind == "raster" and not raster) or (kind == "vector" and not vector):
        raise ValueError("Select a valid raster or vector layer")
    if not raster and not vector:
        raise ValueError("This layer type is not supported")
    if vector:
        if layer.subsetString():
            raise ValueError("This vector layer is filtered. Clear the filter or export the displayed features to a new file.")
        if layer.isEditable() or layer.isModified():
            raise ValueError("Save your edits and stop editing this vector layer, or export an explicit copy first.")
        if layer.selectedFeatureCount():
            raise ValueError("This vector layer has selected features. Clear the selection to use the entire file, or export the selection first.")
    provider = layer.providerType()
    if provider not in {"gdal", "ogr"}:
        raise ValueError("Export this layer to a local GeoTIFF or vector file first")
    decoded = QgsProviderRegistry.instance().decodeUri(provider, layer.source())
    value = decoded.get("path") or decoded.get("uri") or layer.source().split("|", 1)[0]
    if not isinstance(value, str) or value.startswith(("/vsi", "http:", "https:")):
        raise ValueError("Only local file layers are supported; export a copy first")
    path = Path(value).expanduser()
    if path.is_symlink():
        raise ValueError("Select the original file or export this layer; file symlinks can have different adjacent masks or metadata")
    if not path.is_file():
        raise ValueError("The layer does not refer to an existing local file")
    result = {"path": str(path.resolve()), "name": layer.name(), "id": layer.id()}
    if vector:
        if decoded.get("layerName"):
            result["layer"] = decoded["layerName"]
        elif decoded.get("layerId") is not None:
            # OGR layerid identifies a dataset table, not the QGIS display name.
            # Query metadata only (no CountFeatures/ResolveGeometryType flags).
            metadata = QgsProviderRegistry.instance().providerMetadata("ogr")
            number = int(decoded["layerId"])
            names = {detail.name() for detail in metadata.querySublayers(str(path))
                     if detail.layerNumber() == number}
            if len(names) != 1:
                raise ValueError("The dataset layer cannot be identified safely. Export this layer to an explicit local file first.")
            result["layer"] = names.pop()
    return result


def project_layer_sources(kind):
    records = []
    for layer in QgsProject.instance().mapLayers().values():
        try:
            records.append(local_layer_source(layer, kind))
        except (ValueError, OSError):
            continue
    return sorted(records, key=lambda record: record["name"].casefold())


def choose_project_layer(parent, kind):
    records = project_layer_sources(kind)
    if not records:
        raise ValueError("No supported local layers are available. Export remote or memory layers to files first.")
    labels = [f"{record['name']} — {record['path']}"
              + (f" | layer={record['layer']}" if record.get("layer") else "")
              + f" [{record['id']}]" for record in records]
    selected, accepted = QInputDialog.getItem(parent, "Use a QGIS layer",
        "Underlying local file (all features; QGIS display styles are not transformations)", labels, 0, False)
    return records[labels.index(selected)] if accepted else None


class LayerIntegration:
    def __init__(self, logger, iface=None):
        self.logger, self.iface = logger, iface
        self._owned_diagnostics = {}

    @staticmethod
    def _group(run_dir):
        tree = QgsProject.instance().layerTreeRoot()
        root = tree.findGroup("pypopRF") or tree.addGroup("pypopRF")
        key = str(Path(run_dir).resolve())
        for group in root.children():
            if isinstance(group, QgsLayerTreeGroup) and group.customProperty("pypoprf/run_dir") == key:
                return group
        group = root.addGroup(Path(run_dir).name)
        group.setCustomProperty("pypoprf/run_dir", key)
        return group

    def add_run(self, run_dir, paths):
        project = QgsProject.instance()
        key = str(Path(run_dir).resolve())
        group, layers = None, []
        for path in paths:
            path = Path(path).resolve()
            existing = None
            for candidate in project.mapLayers().values():
                if (isinstance(candidate, QgsRasterLayer) and
                        candidate.customProperty("pypoprf/output_path") == str(path)):
                    try:
                        if local_layer_source(candidate, "raster")["path"] == str(path):
                            existing = candidate
                            break
                    except (ValueError, OSError):
                        pass
            if existing:
                layers.append(existing)
                continue
            layer = (self.iface.addRasterLayer(str(path), path.stem) if self.iface
                     else QgsRasterLayer(str(path), path.stem))
            if not layer or not layer.isValid():
                self.logger.warning(f"Could not load result layer: {path}")
                continue
            layer.setCustomProperty("pypoprf/output_path", str(path))
            layer.setCustomProperty("pypoprf/run_dir", key)
            layer.setCustomProperty("pypoprf/units", "persons_per_pixel")
            metadata = layer.metadata()
            metadata.setAbstract("Population count, persons per pixel. Log-spaced display colors do not alter raster values.")
            layer.setMetadata(metadata)
            try:
                self._population_style(layer)
            except Exception as exc:
                self.logger.warning(f"Map loaded with its default style: {exc}")
            if layer.id() not in project.mapLayers():
                project.addMapLayer(layer, False)
            group = group or self._group(run_dir)
            node = project.layerTreeRoot().findLayer(layer.id())
            if node:
                if node.parent() is not group:
                    group.addChildNode(node.clone())
                    node.parent().removeChildNode(node)
            else:
                group.addLayer(layer)
            layer.triggerRepaint()
            layers.append(layer)
        return layers

    @staticmethod
    def _population_style(layer):
        # Omitting stats disambiguates SIP's modern defaulted overload. Passing
        # an IntFlag positionally still selects the deprecated int overload.
        stats = layer.dataProvider().bandStatistics(1, extent=layer.extent(), sampleSize=2048)
        high = float(stats.maximumValue)
        if not math.isfinite(high) or high <= 0:
            return
        ramp = QgsColorRampShader(0, high)
        ramp.setColorRampType(Qgis.ShaderInterpolationMethod.Linear)
        colors = ("#ffffcc", "#a1dab4", "#41b6c4", "#2c7fb8", "#253494")
        breaks = [math.expm1(math.log1p(high) * index / 4) for index in range(5)]
        ramp.setColorRampItemList([QgsColorRampShader.ColorRampItem(value, QColor(color),
            f"{value:,.3g} persons/pixel") for value, color in zip(breaks, colors)])
        shader = QgsRasterShader()
        shader.setRasterShaderFunction(ramp)
        renderer = QgsSingleBandPseudoColorRenderer(layer.dataProvider(), 1, shader)
        renderer.setClassificationMin(0)
        renderer.setClassificationMax(high)
        layer.setRenderer(renderer)

    def show_zone_centroids(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Invalid zone diagnostic data")
        crs = QgsCoordinateReferenceSystem(payload.get("crs") or "")
        if not crs.isValid():
            raise ValueError("These zone centroids have no valid CRS and cannot be mapped safely")
        key = str(Path(payload["run_dir"]).resolve())
        project = QgsProject.instance()
        layer = project.mapLayer(self._owned_diagnostics.get(key, ""))
        try:
            identifier_type = QMetaType.Type.LongLong
        except AttributeError:
            identifier_type = QVariant.LongLong
        existing = (isinstance(layer, QgsVectorLayer) and layer.providerType() == "memory"
            and not layer.isEditable() and not layer.isModified() and layer.fields().names() == ["zone_id"]
            and layer.fields()[0].type() == identifier_type)
        if not existing:
            if layer:
                self.logger.warning("The earlier diagnostic layer was modified or repointed; it is preserved and a new memory layer will be created")
            layer = QgsVectorLayer("Point", "High-error zone centroids — zone validation only", "memory")
            layer.dataProvider().addAttributes([QgsField("zone_id", identifier_type)])
            layer.updateFields()
        features = []
        selected = set(payload.get("zone_ids", []))
        for point in payload.get("centroids", []):
            if point.get("zone_id") not in selected:
                continue
            x, y = float(point["x"]), float(point["y"])
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            feature = QgsFeature(layer.fields())
            feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
            feature.setAttributes([int(point["zone_id"])])
            features.append(feature)
        if not features:
            raise ValueError("No georeferenced high-error centroids were available")
        layer.setCrs(crs)
        if existing:
            layer.dataProvider().deleteFeatures([feature.id() for feature in layer.getFeatures()])
        layer.dataProvider().addFeatures(features)
        layer.updateExtents()
        layer.setCustomProperty("pypoprf/run_dir", key)
        layer.setCustomProperty("pypoprf/diagnostic", "zone_cv_centroids")
        metadata = layer.metadata()
        metadata.setAbstract("Centroids of held-out census zones, not predicted error locations or pixel-accuracy evidence.")
        layer.setMetadata(metadata)
        if not existing:
            project.addMapLayer(layer, False)
            self._group(payload["run_dir"]).addLayer(layer)
            self._owned_diagnostics[key] = layer.id()
        layer.triggerRepaint()
        return layer
