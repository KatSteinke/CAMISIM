#!/usr/bin/env python

__author__ = 'peter hofmann'
__version__ = '0.0.1'

import shutil
import traceback
from fastaanonymizer import FastaAnonymizer
from scripts.Archive.compress import Compress
from scripts.argumenthandler import ArgumentHandler
from scripts.ComunityDesign.communitydesign import CommunityDesign
from scripts.ComunityDesign.taxonomicprofile import TaxonomicProfile
from scripts.GenomePreparation.genomepreparation import GenomePreparation
from scripts.GoldStandardAssembly.goldstandardassembly import GoldStandardAssembly
from scripts.GoldStandardAssembly.samtoolswrapper import SamtoolsWrapper
from scripts.GoldStandardFileFormat.goldstandardfileformat import GoldStandardFileFormat
from scripts.MetaDataTable.metadatatable import MetadataTable
from scripts.NcbiTaxonomy.ncbitaxonomy import NcbiTaxonomy
from scripts.ReadSimulationWrapper.readsimulationwrapper import ReadSimulationArt

# TODO: Pipeline, run twice with different read sim params! New sample folder

class MetagenomeSimulationPipeline(ArgumentHandler):
	"""
	Pipeline for the generation of a simulated metagenome
	"""

	_label = "MetagenomeSimulationPipeline"

	_list_tuple_archive_files = []

	def run_pipeline(self):
		"""
		Run pipeline

		@rtype: None
		"""
		if not self.is_valid():
			self._logger.info("Metagenome simulation aborted")
			return
		self._logger.info("Metagenome simulation starting")
		try:
			# Validate Genomes
			if self._validate_raw_genomes:
				self._logger.info("Validating Genomes")
				self._validate_raw_genomes()

			# Design Communities
			if self._phase_design_community:
				self._logger.info("Design Communities")
				genome_id_to_path_map, list_of_file_paths_distributions = self._design_community()
			else:
				genome_id_to_path_map = self.get_dict_gid_to_genome_file_path()
				directory_out_distributions = self._project_file_folder_handler.get_distribution_dir()
				list_of_file_paths_distributions = CommunityDesign.get_distribution_file_paths(
					directory_out_distributions, self._number_of_samples)

			# Move Genomes
			if self._phase_move_and_clean_genomes:
				self._logger.info("Move Genomes")
				self._move_and_cleanup_genomes(genome_id_to_path_map)

			# Read simulation (Art Illumina)
			if self._phase_simulate_reads:
				self._logger.info("Read simulation")
				for sample_index, file_path_distribution in enumerate(list_of_file_paths_distributions):
					self._simulate_reads(file_path_distribution, sample_index)

			# Generate gold standard assembly
			list_of_output_gsa = None
			file_path_output_gsa_pooled = None
			if self._phase_pooled_gsa:
				self._logger.info("Generate gold standard assembly")
				list_of_output_gsa = self._generate_gsa()

			# Generate gold standard assembly from pooled reads of all samples
			if self._phase_pooled_gsa:
				self._logger.info("Generate pooled strains gold standard assembly")
				file_path_output_gsa_pooled = self._generate_gsa_pooled()

			# Anonymize Data (gsa)
			if self._phase_anonymize:
				self._logger.info("Anonymize Data")
				self._logger.debug(", ".join(list_of_output_gsa))
				self._anonymize_data(list_of_output_gsa, file_path_output_gsa_pooled)

			# Compress Data
			if self._phase_compress:
				self._logger.info("Compress Data")
				self._compress_data()

		except (KeyboardInterrupt, SystemExit, Exception, ValueError, AssertionError, OSError):
			self._logger.error("\n{}\n".format(traceback.format_exc()))
			self._logger.info("Metagenome simulation aborted")
		else:
			self._logger.info("Metagenome simulation finished")

		if not self._debug:
			self._project_file_folder_handler.remove_directory_temp()
		else:
			self._logger.info("Temporary data stored at:\n{}".format(self._project_file_folder_handler.get_tmp_wd()))

	# #########################
	#
	# Validate Genomes
	#
	# #########################

	def _validate_raw_genomes(self):
		"""
		Validate format raw genomes

		@return: True if all genomes valid
		@rtype: bool
		"""
		prepare_genomes = GenomePreparation(
			logfile=self._logfile,
			verbose=self._verbose)

		meta_data_table = MetadataTable(
			separator=self._separator,
			logfile=self._logfile,
			verbose=self._verbose)

		are_valid = True
		for community in self._list_of_communities:
			meta_data_table.read(community.file_path_genome_locations)
			list_of_file_paths = meta_data_table.get_column(1)

			if not prepare_genomes.validate_format(
				list_of_file_paths,
				file_format="fasta",  # TODO: should be done dynamically
				sequence_type="dna",
				ambiguous=True):
				are_valid = False
		return are_valid

	# #########################
	#
	# Design Communities
	#
	# #########################

	def get_dict_gid_to_genome_file_path(self):
		"""
		Get map genome id to genome file path

		@return: Genome id to geone file path
		@rtype: dict[str|unicode, str|unicode]
		"""
		meta_data_table = MetadataTable(
			separator=self._separator,
			logfile=self._logfile,
			verbose=self._verbose)

		file_path_genome_locations = self._project_file_folder_handler.get_genome_location_file_path()
		meta_data_table.read(file_path_genome_locations)
		return meta_data_table.get_map(0, 1)

	def _design_community(self):
		"""
		Start designing sample a community

		@return: map genome id to genome file path and list of distribution file paths
		@rtype: tuple[dict[str|unicode, str|unicode], list[str|unicode]]]
		"""
		meta_data_table = MetadataTable(
			separator=self._separator,
			logfile=self._logfile,
			verbose=self._verbose)

		community_design = CommunityDesign(
			column_name_genome_id=self._column_name_genome_id,
			column_name_otu=self._column_name_otu,
			column_name_novelty_category=self._column_name_novelty_category,
			column_name_ncbi=self._column_name_ncbi,
			column_name_source=self._column_name_source,
			max_processors=self._max_processors,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd(),
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug,
			seed=self._seed
		)

		directory_out_distributions = self._project_file_folder_handler.get_distribution_dir()
		list_of_file_paths_distribution = community_design.get_distribution_file_paths(
			directory_out_distributions, self._number_of_samples)
		directory_out_metadata = self._project_file_folder_handler.get_meta_data_dir()
		directory_simulation_template = self._strain_simulation_template
		merged_genome_id_to_path_map = community_design.design_samples(
			list_of_communities=self._list_of_communities,
			metadata_table=meta_data_table,
			list_of_file_paths_distribution=list_of_file_paths_distribution,
			directory_out_metadata=directory_out_metadata,
			directory_in_template=directory_simulation_template)
		# 	directory_out_distributions=directory_out_distributions,

		taxonomy = NcbiTaxonomy(
			taxonomy_directory=self._directory_ncbi_taxdump,
			build_node_tree=False,
			verbose=self._verbose,
			logfile=self._logfile
		)

		taxonomic_profile = TaxonomicProfile(
			taxonomy=taxonomy,
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug
		)
		taxonomic_profile.write_taxonomic_profile_from_abundance_files(
			metadata_table=meta_data_table,
			list_of_file_paths=list_of_file_paths_distribution,
			directory_output=self._directory_output,
			sample_id=""
		)
		file_path_metadata = self._project_file_folder_handler.get_genome_metadata_file_path()
		meta_data_table.write(file_path_metadata, column_names=True)
		return merged_genome_id_to_path_map, list_of_file_paths_distribution

	# #########################
	#
	# Move Genomes
	#
	# #########################

	def _move_and_cleanup_genomes(self, genome_id_to_path_map):
		"""
		Move genomes, removing sequence descriptions and making sequence names unique

		@param genome_id_to_path_map: A map of genome id to genome file path
		@type genome_id_to_path_map: dict[str|unicode, str|unicode]

		@rtype: None
		"""
		# TODO: Check if already moved!
		# genome_id_to_path_map overwritten with new paths and saved
		prepare_genomes = GenomePreparation(
			logfile=self._logfile,
			verbose=self._verbose)

		directory_output = self._project_file_folder_handler.get_genome_dir()
		prepare_genomes.move_genome_files(
			genome_id_to_path_map=genome_id_to_path_map,
			directory_output=directory_output
			)

		file_path_genome_locations = self._project_file_folder_handler.get_genome_location_file_path()
		prepare_genomes.write_genome_id_to_path_map(genome_id_to_path_map, file_path_genome_locations)

	# #########################
	#
	# Read simulation (Art Illumina)
	#
	# #########################

	def _simulate_reads(self, file_path_distribution, sample_index):
		"""
		Start the simulation of illumina reads

		@param file_path_distribution: File path to a distribution
		@type file_path_distribution: str | unicode
		@param sample_index: Sample index
		@type sample_index: int | long

		@rtype: None
		"""
		self._project_file_folder_handler._location_reads = [True, True]  # TODO write public method for this
		directory_output_tmp = self._project_file_folder_handler.get_fastq_dir(True, sample_index)
		directory_bam = self._project_file_folder_handler.get_bam_dir(sample_index)
		# directory_script = os.path.dirname(__file__)
		# file_path_executable = os.path.join(directory_script, "tools", "readsimulator", "art_illumina")
		# directory_error_profiles = os.path.join(directory_script, "tools", "readsimulator", "profile")

		simulator = ReadSimulationArt(
			file_path_executable=self._executable_art_illumina,
			directory_error_profiles=self._directory_art_error_profiles,
			separator=self._separator,
			max_processes=self._max_processors,
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug,
			seed=self._seed,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd())

		file_path_genome_locations = self._project_file_folder_handler.get_genome_location_file_path()
		simulator.simulate(
			file_path_distribution=file_path_distribution,
			file_path_genome_locations=file_path_genome_locations,
			directory_output=directory_output_tmp,
			total_size=self._sample_size_in_base_pairs,
			profile=self._error_profile,
			fragments_size_mean=self._fragments_size_mean_in_bp,
			fragment_size_standard_deviation=self._fragment_size_standard_deviation_in_bp)

		# convert sam to bam
		samtools = SamtoolsWrapper(
			self._executable_samtools, self._max_processors, self._project_file_folder_handler.get_tmp_wd(), self._logfile, self._verbose
		)

		directory_sam = directory_output_tmp
		samtools.convert_sam_to_bam(directory_sam, directory_bam)

		if not self._phase_anonymize:
			list_of_file_path = self.get_files_in_directory(directory_output_tmp, extension="fq")
			directory_output_fastq = self._project_file_folder_handler.get_fastq_dir(False, sample_index)
			if self._phase_compress:
				for file_path in list_of_file_path:
					self._list_tuple_archive_files.append((file_path, directory_output_fastq))
			else:
				for file_path in list_of_file_path:
					shutil.move(file_path, directory_output_fastq)

	# #########################
	#
	# Generate gold standard assembly
	#
	# #########################

	def _generate_gsa(self):
		"""
		Create a perfect assembly of the reads of each sample.

		@return: List of file paths of assemblies
		@rtype: list[str|unicode]
		"""
		dict_id_to_file_path_fasta = self.get_dict_gid_to_genome_file_path()

		list_of_directory_bam = [
			self._project_file_folder_handler.get_bam_dir(sample_index) for sample_index in range(self._number_of_samples)]
		gs_handler = GoldStandardAssembly(
			file_path_samtools=self._executable_samtools,
			max_processes=self._max_processors,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd(),
			logfile=self._logfile,
			verbose=self._verbose)

		list_of_output_gsa = []
		for directory_bam in list_of_directory_bam:
			dict_id_to_file_path_bam = gs_handler.get_dict_id_to_file_path_bam_from_dir(directory_bam)
			file_path_output_gs = gs_handler.gold_standard_assembly(
				dict_id_to_file_path_bam=dict_id_to_file_path_bam,
				dict_id_to_file_path_fasta=dict_id_to_file_path_fasta)
			list_of_output_gsa.append(file_path_output_gs)

		if not self._phase_anonymize:
			if self._phase_compress:
				for index, file_path in enumerate(list_of_output_gsa):
					directory_output = self._project_file_folder_handler.get_sample_dir(False, index)
					self._list_tuple_archive_files.append((file_path, directory_output))
			else:
				for index, file_path in enumerate(list_of_output_gsa):
					directory_output = self._project_file_folder_handler.get_sample_dir(False, index)
					shutil.move(file_path, directory_output)

		return list_of_output_gsa

	def _generate_gsa_pooled(self):
		"""
		Create a perfect assembly of the reads of all samples.
			merge all sample bam files and create a assembly of all of them
			- create folder reads_on_genomes wherever you are
			- merge bamfiles from list_of_bamdirs into this dirs
			- run gsa for reads_on_genomes
			- create mapping

		@return: file paths of assembly
		@rtype: str|unicode
		"""
		meta_data_table = MetadataTable(
			separator=self._separator,
			logfile=self._logfile,
			verbose=self._verbose)

		gs_handler = GoldStandardAssembly(
			file_path_samtools=self._executable_samtools,
			max_processes=self._max_processors,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd(),
			logfile=self._logfile,
			verbose=self._verbose)

		file_path_genome_locations = self._project_file_folder_handler.get_genome_location_file_path()
		meta_data_table.read(file_path_genome_locations)
		dict_id_to_file_path_fasta = meta_data_table.get_map(0, 1)

		list_of_directory_bam = [
			self._project_file_folder_handler.get_bam_dir(sample_index) for sample_index in range(self._number_of_samples)]

		file_path_output_gsa_pooled = gs_handler.pooled_gold_standard_by_dir(
			list_of_directory_bam, dict_id_to_file_path_fasta)

		if not self._phase_anonymize:
			directory_output = self._project_file_folder_handler.get_output_directory()
			if self._phase_compress:
				self._list_tuple_archive_files.append((file_path_output_gsa_pooled, directory_output))
			else:
				shutil.move(file_path_output_gsa_pooled, directory_output)

		return file_path_output_gsa_pooled

	# #########################
	#
	# Anonymize Data
	#
	# #########################

	def _anonymize_data(self, list_of_output_gsa, file_path_output_gsa_pooled):
		"""
		Anonymize reads and assemblies.

		@param list_of_output_gsa: List of file paths of assemblies
		@type list_of_output_gsa: list[str|unicode]
		@param file_path_output_gsa_pooled: file paths of assembly from all samples
		@type file_path_output_gsa_pooled: str | unicode

		@rtype: None
		"""
		gs_mapping = GoldStandardFileFormat(
			column_name_gid=self._column_name_genome_id,
			column_name_ncbi=self._column_name_ncbi,
			separator=self._separator,
			logfile=self._logfile,
			verbose=self._verbose
		)
		file_path_metadata = self._project_file_folder_handler.get_genome_metadata_file_path()

		directories_fastq_dir_in = [
			self._project_file_folder_handler.get_fastq_dir(True, sample_index)
			for sample_index in range(self._number_of_samples)]

		file_path_genome_locations = self._project_file_folder_handler.get_genome_location_file_path()
		for sample_index in range(self._number_of_samples):
			file_path_anonymous_reads_tmp, file_path_anonymous_mapping_tmp = self._anonymize_reads(
				directories_fastq_dir_in[sample_index],
				sequence_prefix="S{}R".format(sample_index),
				paired_end=True)
			sample_id = str(sample_index)
			file_path_anonymous_reads_out = self._project_file_folder_handler.get_anonymous_reads_file_path(sample_id)
			file_path_anonymous_gs_mapping_out = self._project_file_folder_handler.get_anonymous_reads_map_file_path(sample_id)

			# todo: write to tmp if compressed later
			with open(file_path_anonymous_gs_mapping_out, 'w') as stream_output:
				gs_mapping.gs_read_mapping(
					file_path_genome_locations, file_path_metadata, file_path_anonymous_mapping_tmp, stream_output
				)
			if self._phase_compress:
				self._list_tuple_archive_files.append(
					(file_path_anonymous_reads_tmp, file_path_anonymous_reads_out+".gz"))
				self._list_tuple_archive_files.append(
					(file_path_anonymous_gs_mapping_out, file_path_anonymous_gs_mapping_out+".gz"))
			else:
				shutil.move(file_path_anonymous_reads_tmp, file_path_anonymous_reads_out)

		if not self._phase_gsa and not self._phase_pooled_gsa:
			return

		samtools = SamtoolsWrapper(
			self._executable_samtools, self._max_processors, self._project_file_folder_handler.get_tmp_wd(),
			self._logfile, self._verbose, self._debug)

		if self._phase_gsa:
			for sample_index in range(self._number_of_samples):
				file_path_output_anonymous_gsa, file_path_anonymous_mapping_tmp = self._anonymize_gsa(
					list_of_output_gsa[sample_index],
					"S{}C".format(sample_index))
				sample_id = str(sample_index)
				file_path_output_anonymous_gsa_out = self._project_file_folder_handler.get_anonymous_gsa_file_path(sample_id)
				file_path_anonymous_gsa_mapping_out = self._project_file_folder_handler.get_anonymous_gsa_map_file_path(sample_id)

				list_file_paths_read_positions = [
					samtools.read_start_positions_from_dir_of_bam(self._project_file_folder_handler.get_bam_dir(sample_index))
					]
				with open(file_path_anonymous_gsa_mapping_out, 'w') as stream_output:
					gs_mapping.gs_contig_mapping(
						file_path_genome_locations, file_path_metadata, file_path_anonymous_mapping_tmp, list_file_paths_read_positions, stream_output
					)
				if self._phase_compress:
					self._list_tuple_archive_files.append(
						(file_path_output_anonymous_gsa, file_path_output_anonymous_gsa_out+".gz"))
					self._list_tuple_archive_files.append(
						(file_path_anonymous_gsa_mapping_out, file_path_anonymous_gsa_mapping_out+".gz"))
				else:
					shutil.move(file_path_output_anonymous_gsa, file_path_output_anonymous_gsa_out)

		if self._phase_pooled_gsa:
			file_path_output_anonymous, file_path_anonymous_mapping_tmp = self._anonymize_pooled_gsa(
				file_path_output_gsa_pooled,
				"PC")
			file_path_output_anonymous_out = self._project_file_folder_handler.get_anonymous_gsa_pooled_file_path()
			file_path_anonymous_gsa_mapping_out = self._project_file_folder_handler.get_anonymous_gsa_pooled_map_file_path()

			list_file_paths_read_positions = [
				samtools.read_start_positions_from_dir_of_bam(self._project_file_folder_handler.get_bam_dir(sample_index))
				for sample_index in range(self._number_of_samples)
				]
			with open(file_path_anonymous_gsa_mapping_out, 'w') as stream_output:
				gs_mapping.gs_contig_mapping(
					file_path_genome_locations, file_path_metadata, file_path_anonymous_mapping_tmp, list_file_paths_read_positions, stream_output
				)
			if self._phase_compress:
				self._list_tuple_archive_files.append(
					(file_path_output_anonymous, file_path_output_anonymous_out+".gz"))
				self._list_tuple_archive_files.append(
					(file_path_anonymous_gsa_mapping_out, file_path_anonymous_gsa_mapping_out+".gz"))
			else:
				shutil.move(file_path_output_anonymous, file_path_output_anonymous_out)

	def _anonymize_reads(self, directory_fastq, sequence_prefix, paired_end=True):
		"""
		Anonymize simulated reads.

		@param directory_fastq: fastq directory of a sample
		@type directory_fastq: str | unicode
		@param sequence_prefix: Prefix for anonymous sequence names
		@type sequence_prefix: str | unicode
		@param paired_end: True if reads are paired
		@type paired_end: bool

		@return: File path of anonymized reads and file path of a sequence name mapping
		@rtype: tuple[str|unicode, str|unicode]
		"""
		fastaanonymizer = FastaAnonymizer(
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug,
			seed=self._seed,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd()
		)

		if paired_end:
			file_path_output_anonymous_reads, file_path_anonymous_mapping = fastaanonymizer.interweave_shuffle_anonymize(
				directory_fastq,
				prefix=sequence_prefix,
				file_format="fastq",
				file_extension="fq")
		else:
			file_path_output_anonymous_reads, file_path_anonymous_mapping = fastaanonymizer.shuffle_anonymize(
				directory_fastq,
				prefix=sequence_prefix,
				file_format="fastq",
				file_extension="fq")
		return file_path_output_anonymous_reads, file_path_anonymous_mapping

	def _anonymize_gsa(self, file_path_gsa, sequence_prefix):
		"""
		Anonymize assembly of a sample.

		@param file_path_gsa: file paths of assembly from all samples
		@type file_path_gsa: str | unicode
		@param sequence_prefix: Prefix for anonymous sequence names
		@type sequence_prefix: str | unicode

		@return: File path of anonymized assembly and file path of a sequence name mapping
		@rtype: tuple[str|unicode, str|unicode]
		"""
		fastaanonymizer = FastaAnonymizer(
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug,
			seed=self._seed,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd()
		)

		file_path_output_anonymous_gs, file_path_anonymous_mapping = fastaanonymizer.shuffle_anonymize(
			path_input=file_path_gsa,
			prefix=sequence_prefix,
			file_format="fasta")
		return file_path_output_anonymous_gs, file_path_anonymous_mapping

	def _anonymize_pooled_gsa(
		self, file_path_output_pooled_anonymous, sequence_prefix):
		"""
		Anonymize assembly of a sample.

		@param file_path_output_pooled_anonymous: file paths of assembly from all samples
		@type file_path_output_pooled_anonymous: str | unicode
		@param sequence_prefix: Prefix for anonymous sequence names
		@type sequence_prefix: str | unicode

		@return: File path of anonymized assembly and file path of a sequence name mapping
		@rtype: tuple[str|unicode, str|unicode]
		"""
		fastaanonymizer = FastaAnonymizer(
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug,
			seed=self._seed,
			tmp_dir=self._project_file_folder_handler.get_tmp_wd()
		)

		file_path_output_anonymous, file_path_anonymous_mapping = fastaanonymizer.shuffle_anonymize(
			path_input=file_path_output_pooled_anonymous,
			prefix=sequence_prefix,
			file_format="fasta")

		return file_path_output_anonymous, file_path_anonymous_mapping

	# #########################
	#
	# Compress Data
	#
	# #########################

	def _compress_data(self):
		"""
		Compress files

		@rtype: None
		"""
		compressor = Compress(
			default_compression="gz",
			logfile=self._logfile,
			verbose=self._verbose,
			debug=self._debug)

		compressor.compress_list_tuples(
			self._list_tuple_archive_files,
			compresslevel=self._compresslevel,
			compression_type='gz',
			overwrite=False,
			max_processors=self._max_processors)


if __name__ == "__main__":
	pipeline = MetagenomeSimulationPipeline(
		args=None, version=__version__, separator="\t",
		column_name_genome_id="genome_ID", column_name_otu="OTU", column_name_novelty_category="novelty_category",
		column_name_ncbi="NCBI_ID", column_name_source="source")
	pipeline.run_pipeline()
